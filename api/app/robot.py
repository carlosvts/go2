"""Dona única da conexão WebRTC com o Go2.

O WebRTC é ponto-a-ponto: só existe uma conexão por vez com o robô (é a causa
do `RobotBusyError`). Este módulo concentra essa conexão num único objeto, vivo
pelo tempo do processo, para que os consumidores HTTP não precisem saber nada
de WebRTC. Ver `docs/arquitetura_go2_api.md` seção 3.

Convenção de comentários neste arquivo:

- «padrão exigido pelo webrtc_bridge» — formato ditado pela ponte do robô,
  evidenciado no código da lib (`msgs/pub_sub.py`). Mudar quebra no robô.
- «pendente de validação física» — formato escolhido por nós, ainda não
  confirmado com o robô ligado. Nem a Unitree nem os três `.md` documentam.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import random
import time
from dataclasses import dataclass
from typing import Any

from unitree_webrtc_connect import (
    DATA_CHANNEL_TYPE,
    RTC_TOPIC,
    SPORT_CMD,
    UnitreeWebRTCConnection,
    WebRTCConnectionMethod,
)

from app.config import ConnectionMethod, Settings

log = logging.getLogger(__name__)

_METHOD_MAP = {
    ConnectionMethod.local_sta: WebRTCConnectionMethod.LocalSTA,
    ConnectionMethod.local_ap: WebRTCConnectionMethod.LocalAP,
}


class RobotUnavailableError(RuntimeError):
    """Não há conexão viva com o robô.

    A API nunca reconecta sozinha no meio de um comando: mascarar um robô
    desligado com um retry silencioso esconde exatamente o problema que o
    operador precisa ver.
    """


class RobotTimeoutError(RuntimeError):
    """O robô não respondeu dentro de `GO2_REQUEST_TIMEOUT_S`."""


@dataclass(frozen=True)
class RobotStatus:
    """Snapshot lido do cache em memória — não gera tráfego novo com o robô."""

    connected: bool
    battery_percent: int | None
    mode: int | None
    sport_state_age_s: float | None
    low_state_age_s: float | None


def _first_path(payload: Any, *paths: tuple[str, ...]) -> Any:
    """Devolve o primeiro caminho existente em `payload`, ou `None`.

    O formato exato de `rt/sportmodestate` e `rt/lf/lowstate` não está fixado em
    nenhum dos três documentos de referência, então a extração é feita por
    tentativa entre caminhos plausíveis em vez de assumir um só. Campo não
    reconhecido vira `None` — nunca um valor inventado. `GET /status` também
    devolve o payload cru (`raw`) para permitir fixar esses caminhos na
    primeira validação com o robô ligado.
    """
    for path in paths:
        cursor = payload
        for key in path:
            if not isinstance(cursor, dict) or key not in cursor:
                cursor = None
                break
            cursor = cursor[key]
        if cursor is not None:
            return cursor
    return None


class RobotConnection:
    """Wrapper single-instance da `UnitreeWebRTCConnection`."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._conn: UnitreeWebRTCConnection | None = None
        self._move_task: asyncio.Task[None] | None = None

        # os dicionarios sao exigencia da nova versao gh do legion
        self._sport_state: dict[str, Any] | None = None
        self._sport_state_at: float | None = None
        self._low_state: dict[str, Any] | None = None
        self._low_state_at: float | None = None

        self._speed_level: int | None = None
        """Último nível aplicado via `PUT /commands/speed`, usado como
        fallback quando a resposta do robô não puder ser interpretada."""

    # ─── Ciclo de vida ─────────────────────────────────────────────────────

    async def connect(self) -> None:
        settings = self._settings
        conn = UnitreeWebRTCConnection(
            _METHOD_MAP[settings.connection_method],
            ip=settings.robot_ip,
            serialNumber=settings.robot_serial_number,
            # Firmware < 1.1.15 não exige chave por dispositivo (dossiê 7.3).
            # Se atualizar: aes_128_key=settings.robot_aes_128_key.
        )
        await conn.connect()
        self._conn = conn
        self._subscribe_state()
        # Deixando um emoji para visualizar mais rápido no terminal 
        log.info("🐝 Conectado ao Go2 (%s).", settings.connection_method.value)

    async def disconnect(self) -> None:
        await self._cancel_move()
        if self._conn is not None:
            with contextlib.suppress(Exception):
                await self._conn.disconnect()
            self._conn = None

    @property
    def is_connected(self) -> bool:
        conn = self._conn
        return bool(
            conn is not None
            and conn.isConnected
            and conn.datachannel.data_channel_opened
        )

    # ─── Cache de estado ───────────────────────────────────────────────────

    def _subscribe_state(self) -> None:
        """Assina os tópicos de estado uma única vez, na conexão.

        `GET /status` lê do cache preenchido por estes callbacks, sem
        round-trip novo a cada chamada.
        """
        assert self._conn is not None
        pub_sub = self._conn.datachannel.pub_sub

        # Padrão exigido pelo webrtc_bridge: o callback recebe `{"type",
        # "topic", "data"}` inteiro, e é síncrono — só guarda no cache.
        def on_sport_state(message: dict[str, Any]) -> None:
            self._sport_state = message.get("data")
            self._sport_state_at = time.monotonic()

        def on_low_state(message: dict[str, Any]) -> None:
            self._low_state = message.get("data")
            self._low_state_at = time.monotonic()

        pub_sub.subscribe(RTC_TOPIC["SPORT_MOD_STATE"], on_sport_state)
        pub_sub.subscribe(RTC_TOPIC["LOW_STATE"], on_low_state)

    def status(self) -> RobotStatus:
        now = time.monotonic()
        # Pendente de validação física: caminhos até bateria e modo. Fixar com
        # `GET /status?raw=true` no robô ligado — ver `_first_path`.
        battery = _first_path(
            self._low_state,
            ("bms_state", "soc"),
            ("bms", "soc"),
            ("soc",),
        )
        mode = _first_path(self._sport_state, ("mode",))
        return RobotStatus(
            connected=self.is_connected,
            battery_percent=battery if isinstance(battery, int) else None,
            mode=mode if isinstance(mode, int) else None,
            sport_state_age_s=(
                None if self._sport_state_at is None else now - self._sport_state_at
            ),
            low_state_age_s=(
                None if self._low_state_at is None else now - self._low_state_at
            ),
        )

    @property
    def raw_state(self) -> dict[str, Any | None]:
        return {"sport_mode_state": self._sport_state, "low_state": self._low_state}

    # ─── Envio de comandos ─────────────────────────────────────────────────

    @staticmethod
    def _build_request(api_id: int, parameter: Any = None) -> dict[str, Any]:
        """Monta o envelope de request — padrão exigido pelo webrtc_bridge.

        Réplica de `publish_request_new` (`msgs/pub_sub.py`), necessária porque
        a lib não tem "mandar request sem esperar resposta" — ver `send_sport`.
        Por ser cópia, pode divergir se a lib mudar o formato.
        """
        payload: dict[str, Any] = {
            # Padrão exigido pelo webrtc_bridge: o aninhamento
            # header.identity.{id,api_id}; nenhum dos níveis é opcional.
            "header": {
                "identity": {
                    # Id de correlação que o robô ecoa na resposta: epoch em ms
                    # dobrado para int32 + jitter de desempate. Fórmula da lib.
                    "id": int(time.time() * 1000) % 2147483648 + random.randint(0, 1000),
                    "api_id": api_id,
                }
            },
            # Padrão exigido pelo webrtc_bridge: `parameter` é sempre string, e
            # está presente mesmo sem argumento (vazia).
            "parameter": "",
        }
        if parameter is not None:
            # Padrão exigido pelo webrtc_bridge: parâmetro vai como string JSON,
            # não objeto aninhado. String pronta passa direto, sem duplo encode.
            payload["parameter"] = (
                parameter if isinstance(parameter, str) else json.dumps(parameter)
            )
        return payload

    def send_sport(self, api_id: int, parameter: Any = None) -> None:
        """Envia um comando esportivo sem esperar a resposta do robô.

        É o caminho padrão para todo comando desta versão. Dois motivos:

        1. A API responde ao *aceitar* o comando, não depois que o robô termina
           de se mexer (`docs/arquitetura_go2_api.md` seção 2).
        2. `pub_sub.publish` aguarda um future que nada cancela por timeout, e
           `FutureResolver.pending_callbacks` só é limpo quando a resposta chega.
           Num reenvio a 30Hz, esperar resposta acumularia futures pendentes
           indefinidamente se o robô ficasse mudo.
        """
        if not self.is_connected:
            raise RobotUnavailableError("❌ Sem conexão com o robô.")
        assert self._conn is not None
        # Padrão exigido pelo webrtc_bridge: tópico `rt/api/sport/request` com
        # `type: "req"` — como `msg` (default da lib) o comando não executa.
        self._conn.datachannel.pub_sub.publish_without_callback(
            RTC_TOPIC["SPORT_MOD"],
            self._build_request(api_id, parameter),
            DATA_CHANNEL_TYPE["REQUEST"],
        )

    async def request_sport(self, api_id: int, parameter: Any = None) -> dict[str, Any]:
        """Envia um comando e aguarda a resposta, com timeout próprio."""
        if not self.is_connected:
            raise RobotUnavailableError("❌ Sem conexão com o robô.")
        assert self._conn is not None
        options: dict[str, Any] = {"api_id": api_id}
        if parameter is not None:
            options["parameter"] = parameter
        try:
            return await asyncio.wait_for(
                self._conn.datachannel.pub_sub.publish_request_new(
                    RTC_TOPIC["SPORT_MOD"], options
                ),
                timeout=self._settings.request_timeout_s,
            )
        except asyncio.TimeoutError as exc:
            raise RobotTimeoutError(
                f"❌ Robô não respondeu em {self._settings.request_timeout_s}s."
            ) from exc

    # ─── Postura ───────────────────────────────────────────────────────────

    async def posture(self, command_name: str) -> None:
        """Executa um comando de postura, cancelando qualquer movimento ativo."""
        await self._cancel_move()
        self.send_sport(SPORT_CMD[command_name])

    # ─── Gestos ────────────────────────────────────────────────────────────

    async def gesture(self, command_name: str) -> None:
        """Executa um gesto, cancelando qualquer movimento ativo.

        Pendente de validação física: se o robô ignora um gesto pedido de
        barriga no chão, ou se `StopMove` interrompe um gesto em curso.
        """
        await self._cancel_move()
        self.send_sport(SPORT_CMD[command_name])

    # ─── Movimento contínuo ────────────────────────────────────────────────

    async def start_move(
        self, vx: float, vy: float, vyaw: float, duration_s: float
    ) -> None:
        """Reenvia `Move` a `GO2_MOVE_RATE_HZ` durante `duration_s`.

        Sem lease nesta versão: um novo `move` cancela o anterior.
        """
        await self._cancel_move()
        # Pendente de validação física: nomes do `parameter` do Move (1008).
        # Se o robô ignorar o comando, conferir aqui e em `_move_loop`.
        self.send_sport(SPORT_CMD["Move"], {"x": vx, "y": vy, "yaw": vyaw})
        self._move_task = asyncio.create_task(
            self._move_loop(vx, vy, vyaw, duration_s)
        )

    async def _move_loop(
        self, vx: float, vy: float, vyaw: float, duration_s: float
    ) -> None:
        interval = 1.0 / self._settings.move_rate_hz
        deadline = time.monotonic() + duration_s
        # Pendente de validação física — mesmo payload de `start_move`, manter
        # os dois em sincronia se o formato for corrigido.
        parameter = {"x": vx, "y": vy, "yaw": vyaw}
        try:
            while time.monotonic() < deadline:
                await asyncio.sleep(interval)
                self.send_sport(SPORT_CMD["Move"], parameter)
        except asyncio.CancelledError:
            raise
        except RobotUnavailableError:
            log.warning("❌ Conexão caiu durante o movimento — loop encerrado.")
            return
        except Exception:
            log.exception("❌ Falha no loop de movimento.")
            return
        # Fim da janela: para explicitamente em vez de depender do watchdog
        # interno do robô.
        with contextlib.suppress(RobotUnavailableError):
            self.send_sport(SPORT_CMD["StopMove"])

    async def _cancel_move(self) -> None:
        task, self._move_task = self._move_task, None
        if task is not None and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    async def stop(self) -> None:
        """Parada imediata: cancela o reenvio e manda `StopMove`.

        Para desenergizar as juntas use `POST /commands/posture` com `damp`.
        """
        await self._cancel_move()
        self.send_sport(SPORT_CMD["StopMove"])

    # ─── Velocidade ────────────────────────────────────────────────────────

    async def set_speed_level(self, level: int) -> None:
        # Pendente de validação física: o envelope `{"data": <nível>}` do
        # SpeedLevel (1015) não está nos três `.md` nem no código da lib.
        self.send_sport(SPORT_CMD["SpeedLevel"], {"data": level})
        self._speed_level = level

    async def get_speed_level(self) -> tuple[int | None, Any]:
        """Consulta `GetSpeedLevel`; devolve `(nível, resposta crua)`.

        O formato da resposta não está documentado em nenhum dos três `.md`, então
        o nível é extraído por tentativa e vem `None` se nenhum caminho bater —
        o payload cru acompanha a resposta para permitir fixar isso na primeira
        validação com o robô ligado.
        """
        response = await self.request_sport(SPORT_CMD["GetSpeedLevel"])
        # Padrão exigido pelo webrtc_bridge: a resposta vem embrulhada em
        # `data`, igual às mensagens de estado.
        data = response.get("data") if isinstance(response, dict) else None
        # Pendente de validação física: onde, dentro de `data`, está o nível.
        level = _first_path(data, ("data",), ("level",), ("speed_level",))
        if isinstance(level, str):
            with contextlib.suppress(ValueError):
                level = int(level)
        return (level if isinstance(level, int) else None), data
