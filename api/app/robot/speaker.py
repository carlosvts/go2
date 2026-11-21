"""Alto-falante do robô pela track de áudio WebRTC (F-007, `/speaker/*`).

O arquivo é decodificado inteiro, numa thread, para PCM 48 kHz estéreo s16
em memória. Uma :class:`SpeakerTrack` por conexão, posta no transceiver de
áudio no primeiro `play`, nunca termina: ociosa entrega silêncio, tocando
entrega o PCM. Nada disso foi visto no robô (F-007 A10).
"""

import asyncio
import io
import logging
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from fractions import Fraction
from typing import Any, Literal

import av
import numpy as np
from aiortc import MediaStreamTrack
from numpy.typing import NDArray

from app.exceptions import RobotUnavailableError, UnsupportedAudioError
from app.robot.connection import ConnectionState
from app.robot.link import NOT_CONNECTED_MESSAGE, RobotLink

log = logging.getLogger(__name__)

SAMPLE_RATE = 48_000
CHANNELS = 2
FRAME_SAMPLES = SAMPLE_RATE // 50
"""Amostras por quadro: 20 ms a 48 kHz."""

_TIME_BASE = Fraction(1, SAMPLE_RATE)

Pcm = NDArray[np.int16]
"""PCM `(amostras, 2)`, int16 intercalado."""


@dataclass(frozen=True)
class AudioClip:
    """Arquivo já decodificado para 48 kHz estéreo s16."""

    name: str
    pcm: Pcm

    @property
    def duration_s(self) -> float:
        """Amostras ÷ taxa."""
        return float(self.pcm.shape[0] / SAMPLE_RATE)


def _sniff(data: bytes) -> str | None:
    """`wav` ou `mp3` pelo conteúdo (cabeçalho), ou `None`."""
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WAVE":  # noqa: PLR2004
        return "wav"
    if data[:3] == b"ID3":
        return "mp3"
    # Sincronismo de quadro MPEG (11 bits 1) com layer III.
    if len(data) >= 2 and data[0] == 0xFF and data[1] & 0xE6 == 0xE2:  # noqa: PLR2004
        return "mp3"
    return None


def decode_audio(data: bytes, name: str) -> AudioClip:
    """Decodifica WAV ou MP3 inteiro para PCM 48 kHz estéreo s16 (PyAV).

    Pesa na CPU: chame fora do event loop.

    Raises:
        UnsupportedAudioError: formato não reconhecido pelo conteúdo, arquivo
            que não decodifica ou sem amostras.
    """
    fmt = _sniff(data)
    if fmt is None:
        msg = "❌ O arquivo não é WAV nem MP3."
        raise UnsupportedAudioError(msg)
    chunks: list[NDArray[Any]] = []
    try:
        with av.open(io.BytesIO(data), mode="r", format=fmt) as container:
            stream = container.streams.audio[0]
            resampler = av.AudioResampler(
                format="s16", layout="stereo", rate=SAMPLE_RATE
            )
            for frame in container.decode(stream):
                chunks.extend(out.to_ndarray() for out in resampler.resample(frame))
            chunks.extend(out.to_ndarray() for out in resampler.resample(None))
    except (av.FFmpegError, IndexError, ValueError, OSError) as exc:
        msg = f"❌ Não foi possível decodificar o {fmt.upper()}: {exc}"
        raise UnsupportedAudioError(msg) from exc
    if not chunks:
        msg = f"❌ O {fmt.upper()} não tem áudio."
        raise UnsupportedAudioError(msg)
    pcm = np.concatenate([chunk.reshape(-1) for chunk in chunks]).reshape(-1, CHANNELS)
    if pcm.shape[0] == 0:
        msg = f"❌ O {fmt.upper()} não tem áudio."
        raise UnsupportedAudioError(msg)
    return AudioClip(name=name, pcm=np.ascontiguousarray(pcm, dtype=np.int16))


class SpeakerTrack(MediaStreamTrack):
    """Track de áudio persistente: silêncio ou o PCM atual, em tempo real.

    `recv()` nunca lança: se lançasse `MediaStreamError`, o laço de envio do
    aiortc terminaria e nada mais sairia nesta conexão. Roda no event loop
    (a codificação Opus o aiortc faz num executor).
    """

    kind = "audio"

    def __init__(
        self,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Any] = asyncio.sleep,
    ) -> None:
        """Começa ociosa; `clock`/`sleep` existem para testes."""
        super().__init__()
        self._clock = clock
        self._sleep = sleep
        self._start: float | None = None
        self._timestamp = 0
        self._pcm: Pcm | None = None
        self._offset = 0
        self._on_end: Callable[[], None] | None = None
        self._silence = np.zeros((1, FRAME_SAMPLES * CHANNELS), dtype=np.int16)

    @property
    def playing(self) -> bool:
        """Há PCM sendo entregue."""
        return self._pcm is not None

    def play(self, pcm: Pcm, on_end: Callable[[], None]) -> None:
        """Troca o que toca a partir do próximo quadro; `on_end` ao acabar."""
        self._pcm = pcm
        self._offset = 0
        self._on_end = on_end

    def silence(self) -> None:
        """Volta ao silêncio no próximo quadro, sem chamar `on_end`."""
        self._pcm = None
        self._on_end = None

    async def recv(self) -> av.AudioFrame:
        """Próximo quadro de 20 ms, no ritmo do relógio real."""
        if self._start is None:
            self._start = self._clock()
        else:
            self._timestamp += FRAME_SAMPLES
            wait = self._start + self._timestamp / SAMPLE_RATE - self._clock()
            if wait > 0:
                await self._sleep(wait)
        frame = av.AudioFrame.from_ndarray(
            self._next_samples(), format="s16", layout="stereo"
        )
        frame.sample_rate = SAMPLE_RATE
        frame.pts = self._timestamp
        frame.time_base = _TIME_BASE
        return frame

    def _next_samples(self) -> NDArray[np.int16]:
        pcm = self._pcm
        if pcm is None:
            return self._silence
        chunk = pcm[self._offset : self._offset + FRAME_SAMPLES]
        self._offset += FRAME_SAMPLES
        if chunk.shape[0] < FRAME_SAMPLES:
            padded = np.zeros((FRAME_SAMPLES, CHANNELS), dtype=np.int16)
            padded[: chunk.shape[0]] = chunk
            chunk = padded
        if self._offset >= pcm.shape[0]:
            on_end = self._on_end
            self.silence()
            if on_end is not None:
                try:
                    on_end()
                except Exception:
                    log.exception("❌ Falha ao marcar o fim do áudio.")
        return np.ascontiguousarray(chunk).reshape(1, -1)


SpeakerState = Literal["idle", "playing"]


def _iso(moment: datetime | None) -> str | None:
    """ISO 8601 com `Z`, igual ao que o pydantic gera no `GET /speaker`."""
    if moment is None:
        return None
    return moment.isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class SpeakerSnapshot:
    """O que o alto-falante está fazendo (`GET /speaker`)."""

    state: SpeakerState
    playback_id: str | None = None
    name: str | None = None
    started_at: datetime | None = None
    duration_s: float | None = None

    def as_dict(self) -> dict[str, Any]:
        """Dict pronto para JSON, o mesmo corpo do `GET /speaker`."""
        return {
            "state": self.state,
            "playback_id": self.playback_id,
            "name": self.name,
            "started_at": _iso(self.started_at),
            "duration_s": self.duration_s,
        }


IDLE = SpeakerSnapshot(state="idle")


@dataclass(frozen=True)
class Playback:
    """Um `play` aceito (`202`)."""

    playback_id: str
    name: str
    duration_s: float


SpeakerListener = Callable[[dict[str, Any]], None]
"""Recebe :meth:`SpeakerSnapshot.as_dict` a cada mudança `idle`/`playing`."""

Decoder = Callable[[bytes, str], AudioClip]


def _default_decoder(data: bytes, name: str) -> AudioClip:
    # Busca no módulo a cada chamada: os testes trocam `decode_audio`.
    return decode_audio(data, name)


def _utc_now() -> datetime:
    return datetime.now(UTC)


class Speaker:
    """Um áudio por vez, sem corrida entre `play` e `stop`.

    Cada `play` e cada `stop` recebe um número de ordem (geração). Um `play`
    só toca se nenhum `play` ou `stop` mais novo chegou enquanto ele
    decodificava. A queda da conexão cala e volta a `idle`; nada volta a tocar
    sozinho na conexão nova.
    """

    def __init__(
        self,
        link: RobotLink,
        *,
        decoder: Decoder = _default_decoder,
        track_factory: Callable[[], SpeakerTrack] = SpeakerTrack,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        """Recebe o link; os demais existem para testes."""
        self._link = link
        self._decoder = decoder
        self._track_factory = track_factory
        self._clock = clock
        self._generation = 0
        self._track: SpeakerTrack | None = None
        self._track_key: object | None = None
        self._snapshot = IDLE
        self._listeners: list[SpeakerListener] = []
        link.state.subscribe(self._on_connection_change)

    @property
    def snapshot(self) -> SpeakerSnapshot:
        """Estado atual."""
        return self._snapshot

    def subscribe(self, listener: SpeakerListener) -> None:
        """Registra `listener` para cada mudança `idle`/`playing` (gancho F-004).

        É chamado no event loop, com o mesmo dict do `GET /speaker`. Exceções
        do ouvinte são registradas no log e ignoradas.
        """
        self._listeners.append(listener)

    async def play(self, data: bytes, name: str) -> Playback:
        """Decodifica `data` numa thread e passa a tocar, substituindo o atual.

        Se um `play` ou `stop` mais novo chegar durante a decodificação, este
        termina sem tocar (devolve o `Playback` mesmo assim: foi aceito e
        logo substituído).

        Raises:
            RobotUnavailableError: sem conexão, antes ou depois de decodificar
                (inclusive se a conexão mudou no meio).
            UnsupportedAudioError: não é WAV/MP3 ou não decodifica.
        """
        self._link.ensure_connected()
        self._generation += 1
        generation = self._generation
        key = self._link.connection_key
        clip = await asyncio.to_thread(self._decoder, data, name)
        playback = Playback(
            playback_id=uuid.uuid4().hex, name=name, duration_s=clip.duration_s
        )
        if generation != self._generation:
            log.info("🔇 Áudio %r substituído antes de tocar.", name)
            return playback
        if not self._link.is_connected or self._link.connection_key is not key:
            raise RobotUnavailableError(NOT_CONNECTED_MESSAGE)
        track = self._current_track()
        track.play(clip.pcm, lambda: self._on_clip_end(playback.playback_id))
        self._set(
            SpeakerSnapshot(
                state="playing",
                playback_id=playback.playback_id,
                name=name,
                started_at=self._clock(),
                duration_s=playback.duration_s,
            )
        )
        return playback

    async def stop(self) -> SpeakerSnapshot:
        """Cala o alto-falante e cancela `play` em decodificação (gancho F-006).

        Vale também quando nada tocava. Async para o `POST /audio/silence`
        poder aguardá-lo; não fala com o robô.
        """
        self._generation += 1
        if self._track is not None:
            self._track.silence()
        self._set(IDLE)
        return self._snapshot

    def _current_track(self) -> SpeakerTrack:
        """A track da conexão atual, instalando uma nova se a conexão mudou."""
        key = self._link.connection_key
        if self._track is None or self._track_key is not key:
            track = self._track_factory()
            self._track_key = self._link.attach_audio_track(track)
            self._track = track
        return self._track

    def _on_clip_end(self, playback_id: str) -> None:
        if self._snapshot.playback_id == playback_id:
            self._set(IDLE)

    def _on_connection_change(self, payload: dict[str, str]) -> None:
        if payload.get("state") == ConnectionState.connected.value:
            return
        if self._track is not None:
            self._track.silence()
        self._track = None
        self._track_key = None
        self._set(IDLE)

    def _set(self, snapshot: SpeakerSnapshot) -> None:
        if snapshot == self._snapshot:
            return
        self._snapshot = snapshot
        message = snapshot.as_dict()
        for listener in self._listeners:
            try:
                listener(message)
            except Exception:
                log.exception("❌ Falha num ouvinte do alto-falante.")
