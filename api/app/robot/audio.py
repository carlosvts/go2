"""Biblioteca de áudio guardada no robô: `/audio/*` (F-006).

Listar, enviar, renomear, apagar, tocar, pausar, retomar, modo de reprodução
e silenciar, pelo hub de áudio (`rt/api/audiohub/request`). O formato da
lista e do modo vem do exemplo da lib e não foi visto no robô (`inferido`).

Dois ganchos para outras features:

- :meth:`AudioHub.set_speaker_stopper`: o `POST /audio/silence` também para o
  alto-falante da F-007;
- :meth:`AudioHub.subscribe_player_state`: o `data` cru de cada
  `AUDIO_HUB_PLAY_STATE`, para o `/ws/state` da F-004.
"""

import asyncio
import contextlib
import json
import logging
import time
import unicodedata
import uuid
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import Any

from app.exceptions import (
    ConflictError,
    InvalidCommandError,
    NotFoundError,
    RobotRejectedError,
    RobotTimeoutError,
    RobotUnavailableError,
)
from app.robot.audio_format import AudioConverter
from app.robot.channel import AudioHubChannel
from app.robot.device import VuiResponse
from app.robot.link import RobotLink
from app.robot.ports import PubSub
from app.robot.unitree import (
    AUDIO_UPLOAD_BLOCK_INTERVAL_S,
    RTC_TOPIC,
    AudioUploadBlocks,
)

log = logging.getLogger(__name__)

MAX_NAME_CHARS = 64
UPLOAD_HISTORY = 20

SpeakerStopper = Callable[[], Awaitable[None]]
"""Para o alto-falante da F-007; registrado por quem o implementa."""

PlayerStateListener = Callable[[Any], None]
"""Recebe o `data` cru de cada `AUDIO_HUB_PLAY_STATE`. Síncrono e rápido."""


class PlayMode(StrEnum):
    """Modos de reprodução da docstring de `set_play_mode` da lib (`inferido`)."""

    single_cycle = "single_cycle"
    no_cycle = "no_cycle"
    list_loop = "list_loop"


class UploadState(StrEnum):
    """Estado de um envio."""

    uploading = "uploading"
    done = "done"
    failed = "failed"


@dataclass(frozen=True)
class AudioFile:
    """Um item da lista: `UNIQUE_ID`, `CUSTOM_NAME` e o resto, sem interpretar."""

    id: str
    name: str
    extra: dict[str, Any]


@dataclass(frozen=True)
class PlayerReading:
    """Último `data` de `AUDIO_HUB_PLAY_STATE` e há quanto tempo chegou."""

    data: Any
    age_s: float | None


@dataclass(frozen=True)
class UploadSource:
    """O que veio no `POST /audio/files`: bytes, nome do arquivo e `name`."""

    data: bytes
    filename: str | None
    name: str | None


@dataclass
class UploadRecord:
    """Estado de um envio, lido por `GET /audio/uploads/{upload_id}`."""

    upload_id: str
    name: str
    total_chunks: int
    state: UploadState = UploadState.uploading
    sent_chunks: int = 0
    file_id: str | None = None
    error: str | None = None
    before_ids: frozenset[str] = field(default_factory=frozenset, repr=False)


UploadReader = Callable[[], Awaitable[UploadSource]]
"""Lê o corpo do pedido; só é chamado depois de reservar a vaga do envio."""


class AudioName:
    r"""Regra do nome no robô: 1–64 caracteres, sem `/`, `\` nem controle."""

    @staticmethod
    def validate(raw: str) -> str:
        """Devolve o nome sem espaços nas pontas.

        Raises:
            InvalidCommandError: fora da regra (vira `422`).
        """
        name = raw.strip()
        if not 1 <= len(name) <= MAX_NAME_CHARS:
            msg = f"❌ O nome precisa ter de 1 a {MAX_NAME_CHARS} caracteres."
            raise InvalidCommandError(msg)
        if any(c in "/\\" or unicodedata.category(c) == "Cc" for c in name):
            msg = "❌ O nome não pode ter `/`, `\\` nem caracteres de controle."
            raise InvalidCommandError(msg)
        return name

    @classmethod
    def of(cls, source: UploadSource) -> str:
        """`name` do formulário ou, se ausente ou vazio, o arquivo sem extensão."""
        if source.name:
            return cls.validate(source.name)
        filename = (source.filename or "").replace("\\", "/").rsplit("/", 1)[-1]
        stem = filename.rsplit(".", 1)[0] if "." in filename else filename
        return cls.validate(stem)


class AudioHubResponse:
    """Interpreta as respostas do hub; o que não bate vira `502`."""

    @staticmethod
    def decoded_data(response: object) -> object:
        """Exige o aceite e decodifica `data.data` (string JSON).

        Raises:
            RobotRejectedError: recusa, ou `data.data` ausente ou não JSON.
        """
        VuiResponse.ensure_accepted(response)
        data = response.get("data") if isinstance(response, dict) else None
        raw = data.get("data") if isinstance(data, dict) else None
        if not isinstance(raw, str):
            msg = "❌ Resposta do hub sem data.data em texto."
            raise RobotRejectedError(msg)
        try:
            return json.loads(raw)
        except ValueError as exc:
            msg = "❌ data.data da resposta do hub não é JSON."
            raise RobotRejectedError(msg) from exc

    @classmethod
    def files(cls, response: object) -> list[AudioFile]:
        """Lê `audio_list`: cada item com `UNIQUE_ID` e `CUSTOM_NAME` em texto.

        Raises:
            RobotRejectedError: recusa ou lista malformada.
        """
        decoded = cls.decoded_data(response)
        items = decoded.get("audio_list") if isinstance(decoded, dict) else None
        if not isinstance(items, list):
            msg = "❌ Resposta do hub sem a lista audio_list."
            raise RobotRejectedError(msg)
        files = []
        for item in items:
            if not isinstance(item, dict):
                msg = "❌ Item da audio_list não é objeto."
                raise RobotRejectedError(msg)
            file_id, name = item.get("UNIQUE_ID"), item.get("CUSTOM_NAME")
            if not isinstance(file_id, str) or not isinstance(name, str):
                msg = "❌ Item da audio_list sem UNIQUE_ID ou CUSTOM_NAME em texto."
                raise RobotRejectedError(msg)
            extra = {
                k: v for k, v in item.items() if k not in {"UNIQUE_ID", "CUSTOM_NAME"}
            }
            files.append(AudioFile(id=file_id, name=name, extra=extra))
        return files

    @classmethod
    def play_mode(cls, response: object) -> PlayMode:
        """Lê `play_mode` de `data.data` (formato `inferido`, simétrico ao `SET`).

        Raises:
            RobotRejectedError: recusa, campo ausente ou modo desconhecido.
        """
        decoded = cls.decoded_data(response)
        mode = decoded.get("play_mode") if isinstance(decoded, dict) else None
        if not isinstance(mode, str) or mode not in {m.value for m in PlayMode}:
            msg = f"❌ Modo de reprodução ilegível na resposta do hub: {mode!r}."
            raise RobotRejectedError(msg)
        return PlayMode(mode)


def _json(parameter: dict[str, Any]) -> str:
    """`parameter` como a lib manda: `json.dumps` do dicionário."""
    return json.dumps(parameter)


class AudioHub:
    """Chamadas ao hub de áudio, envio em segundo plano e estado do player.

    Toda chamada espera o aceite (`header.status.code == 0`) com o timeout
    do canal. Nada aqui mexe no movimento.
    """

    def __init__(  # noqa: PLR0913 - colaboradores e ajustes de teste, por nome
        self,
        channel: AudioHubChannel,
        link: RobotLink,
        *,
        max_upload_bytes: int,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[object]] = asyncio.sleep,
        history: int = UPLOAD_HISTORY,
    ) -> None:
        """Recebe o canal, a conexão e o limite do WAV enviado.

        Args:
            channel: Canal do hub.
            link: Conexão; a identidade do data channel detecta queda.
            max_upload_bytes: Teto do arquivo recebido e do WAV enviado.
            clock: Relógio da idade do player (injetável).
            sleep: Espera entre blocos (injetável).
            history: Quantos envios guardar.
        """
        self._channel = channel
        self._link = link
        self._max_upload_bytes = max_upload_bytes
        self._clock = clock
        self._sleep = sleep
        self._history = history
        self.block_interval_s = AUDIO_UPLOAD_BLOCK_INTERVAL_S
        """Intervalo entre blocos (0,1 s, da lib); testes zeram."""
        self._uploads: OrderedDict[str, UploadRecord] = OrderedDict()
        self._busy = False
        self._task: asyncio.Task[None] | None = None
        self._current: UploadRecord | None = None
        self._speaker_stopper: SpeakerStopper | None = None
        self._player_data: Any = None
        self._player_at: float | None = None
        self._player_listeners: list[PlayerStateListener] = []

    @property
    def max_upload_bytes(self) -> int:
        """Teto do arquivo recebido e do WAV enviado, em bytes."""
        return self._max_upload_bytes

    # ─── Ganchos ───────────────────────────────────────────────────────────

    def set_speaker_stopper(self, stopper: SpeakerStopper | None) -> None:
        """Registra (ou remove, com `None`) quem para o alto-falante (F-007)."""
        self._speaker_stopper = stopper

    def subscribe_player_state(
        self, listener: PlayerStateListener
    ) -> Callable[[], None]:
        """Registra `listener` para o `data` cru de cada `AUDIO_HUB_PLAY_STATE`.

        Returns:
            Função que cancela o registro.
        """
        self._player_listeners.append(listener)

        def unsubscribe() -> None:
            with contextlib.suppress(ValueError):
                self._player_listeners.remove(listener)

        return unsubscribe

    # ─── Player ────────────────────────────────────────────────────────────

    def attach(self, pub_sub: PubSub) -> None:
        """Assina `AUDIO_HUB_PLAY_STATE`; refeito a cada conexão."""
        pub_sub.subscribe(RTC_TOPIC["AUDIO_HUB_PLAY_STATE"], self.on_player_state)

    def on_player_state(self, message: dict[str, Any]) -> None:
        """Guarda o `data` cru e o repassa aos ouvintes."""
        data = message.get("data")
        self._player_data = data
        self._player_at = self._clock()
        for listener in list(self._player_listeners):
            try:
                listener(data)
            except Exception:
                log.exception("❌ Falha num ouvinte do estado do player.")

    def player(self) -> PlayerReading:
        """Último estado do player, sem falar com o robô."""
        age = None if self._player_at is None else self._clock() - self._player_at
        return PlayerReading(data=self._player_data, age_s=age)

    # ─── Chamadas ao hub ───────────────────────────────────────────────────

    async def _call(self, command: str, parameter: dict[str, Any]) -> None:
        response = await self._channel.request(command, _json(parameter))
        VuiResponse.ensure_accepted(response)

    async def list_files(self) -> list[AudioFile]:
        """Lista os áudios guardados no robô (1001)."""
        response = await self._channel.request("GET_AUDIO_LIST", _json({}))
        return AudioHubResponse.files(response)

    async def rename(self, file_id: str, name: str) -> None:
        """Renomeia (1008); `name` já validado."""
        await self._call("SELECT_RENAME", {"unique_id": file_id, "new_name": name})

    async def delete(self, file_id: str) -> None:
        """Apaga (1009)."""
        await self._call("SELECT_DELETE", {"unique_id": file_id})

    async def play(self, file_id: str) -> None:
        """Toca (1002). O aceite não quer dizer que o som terminou."""
        await self._call("SELECT_START_PLAY", {"unique_id": file_id})

    async def pause(self) -> None:
        """Pausa (1003)."""
        await self._call("PAUSE", {})

    async def resume(self) -> None:
        """Retoma (1004)."""
        await self._call("UNSUSPEND", {})

    async def get_play_mode(self) -> PlayMode:
        """Lê o modo de reprodução (1010)."""
        response = await self._channel.request("GET_PLAY_MODE", _json({}))
        return AudioHubResponse.play_mode(response)

    async def set_play_mode(self, mode: PlayMode) -> None:
        """Define o modo de reprodução (1007)."""
        await self._call("SET_PLAY_MODE", {"play_mode": mode.value})

    async def silence(self) -> None:
        """Para o alto-falante (se registrado) e pausa o hub.

        O alto-falante vem primeiro por ser local e rápido. Um não depende do
        outro: se um falha, o outro ainda é tentado; o erro do `PAUSE` tem
        precedência na resposta.
        """
        stopper_error: Exception | None = None
        if self._speaker_stopper is not None:
            try:
                await self._speaker_stopper()
            except Exception as exc:
                log.exception("❌ Falha ao parar o alto-falante.")
                stopper_error = exc
        await self.pause()
        if stopper_error is not None:
            raise stopper_error

    # ─── Envio ─────────────────────────────────────────────────────────────

    async def upload(self, read: UploadReader) -> UploadRecord:
        """Valida, converte e começa o envio em segundo plano.

        A vaga (um envio por vez) é reservada antes de ler o corpo, e
        liberada se algo falhar antes do `202`.

        Raises:
            ConflictError: já há envio em andamento, ou o nome já existe.
            InvalidCommandError: nome inválido.
            PayloadTooLargeError: arquivo ou WAV final acima do limite.
            UnsupportedMediaError: não é WAV nem MP3, ou não decodifica.
            RobotUnavailableError, RobotTimeoutError, RobotRejectedError: na
                consulta da lista.
        """
        if self._busy:
            msg = "❌ Já há um envio de áudio em andamento."
            raise ConflictError(msg)
        self._busy = True
        try:
            record, blocks = await self._prepare(read)
        except BaseException:
            self._busy = False
            raise
        self._remember(record)
        datachannel = self._link.datachannel
        self._current = record
        self._task = asyncio.create_task(self._send(record, blocks, datachannel))
        return replace(record)

    async def _prepare(
        self, read: UploadReader
    ) -> tuple[UploadRecord, AudioUploadBlocks]:
        source = await read()
        name = AudioName.of(source)
        prepared = await asyncio.to_thread(
            AudioConverter.prepare, source.data, self._max_upload_bytes
        )
        files = await self.list_files()
        if any(f.name == name for f in files):
            msg = f"❌ Já existe um áudio chamado {name!r} no robô."
            raise ConflictError(msg)
        blocks = AudioUploadBlocks(prepared.wav, name)
        record = UploadRecord(
            upload_id=uuid.uuid4().hex,
            name=name,
            total_chunks=blocks.total,
            before_ids=frozenset(f.id for f in files),
        )
        return record, blocks

    def _remember(self, record: UploadRecord) -> None:
        self._uploads[record.upload_id] = record
        while len(self._uploads) > self._history:
            self._uploads.popitem(last=False)

    def upload_status(self, upload_id: str) -> UploadRecord:
        """Cópia do estado de um envio.

        Raises:
            NotFoundError: `upload_id` desconhecido ou já esquecido.
        """
        record = self._uploads.get(upload_id)
        if record is None:
            msg = f"❌ Envio {upload_id!r} desconhecido."
            raise NotFoundError(msg)
        return replace(record)

    async def cancel_upload(self) -> None:
        """Interrompe o envio em curso, que vira `failed: disconnected`."""
        task, record = self._task, self._current
        if task is None or task.done():
            return
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        # Cancelada antes de começar, a tarefa não passa pelo `except` de `_send`.
        if record is not None and record.state is UploadState.uploading:
            self._fail(record, "disconnected")
        self._busy = False
        self._task = None

    async def _send(
        self, record: UploadRecord, blocks: AudioUploadBlocks, datachannel: object
    ) -> None:
        """Manda os blocos em ordem; para no primeiro problema."""
        try:
            for index in range(1, blocks.total + 1):
                if index > 1:
                    await self._sleep(self.block_interval_s)
                if self._link.datachannel is not datachannel:
                    self._fail(record, "disconnected")
                    return
                parameter = blocks.parameter(index, int(time.time() * 1000))
                response = await self._channel.request("UPLOAD_AUDIO_FILE", parameter)
                VuiResponse.ensure_accepted(response)
                record.sent_chunks = index
            record.file_id = await self._new_file_id(record)
            record.state = UploadState.done
            log.info("🎵 Áudio %r enviado (%d blocos).", record.name, blocks.total)
        except RobotTimeoutError:
            self._fail(record, "timeout")
        except RobotUnavailableError:
            self._fail(record, "disconnected")
        except RobotRejectedError as exc:
            self._fail(record, f"rejected: {exc}")
        except asyncio.CancelledError:
            self._fail(record, "disconnected")
            raise
        except Exception as exc:
            log.exception("❌ Falha inesperada no envio de áudio.")
            self._fail(record, f"error: {type(exc).__name__}")
        finally:
            self._busy = False
            self._task = None

    @staticmethod
    def _fail(record: UploadRecord, error: str) -> None:
        record.state = UploadState.failed
        record.error = error
        log.warning("❌ Envio de áudio %r falhou: %s.", record.name, error)

    async def _new_file_id(self, record: UploadRecord) -> str | None:
        """Id que não existia antes do envio; `None` se não aparecer.

        Com mais de um id novo (outro cliente enviou ao mesmo tempo), fica o
        de mesmo nome. Falha na consulta não desfaz o `done`: os blocos foram
        aceitos.
        """
        try:
            files = await self.list_files()
        except (RobotTimeoutError, RobotUnavailableError, RobotRejectedError):
            log.warning("❌ Lista indisponível depois do envio de %r.", record.name)
            return None
        new = [f for f in files if f.id not in record.before_ids]
        if len(new) == 1:
            return new[0].id
        named = [f for f in new if f.name == record.name]
        return named[0].id if len(named) == 1 else None
