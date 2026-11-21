"""LiDAR do robô para os streams `/ws/lidar` (F-001) e `/ws/telemetry` (F-002).

Fluxo dos dados:

```
callback da lib (loop) ─▶ fila do decoder (descarta a mais antiga)
   ─▶ worker único (thread) decodifica e monta o frame
   ─▶ fila de cada cliente de /ws/lidar (descarta o mais antigo)
   └▶ métricas da janela ─▶ lidar_metrics em /ws/telemetry
ROBOTODOM / ULIDAR_STATE (loop) ─▶ JSON uma vez ─▶ clientes de /ws/telemetry
```

Refcount: o LiDAR fica assinado enquanto há cliente em qualquer das duas
rotas e conexão; os tópicos extras, enquanto há cliente de telemetria. Ativar
e desativar passam por uma única tarefa, que reavalia o estado até ele
estabilizar: corridas entre clientes que chegam e saem e a conexão que cai e
volta se resolvem nela.
"""

import asyncio
import contextlib
import json
import logging
import struct
import time
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any

import numpy as np
from numpy.typing import NDArray

from app.robot.clients import ClientMessage
from app.robot.connection import ConnectionState
from app.robot.link import RobotLink
from app.robot.ports import DataChannel
from app.robot.streams import DropOldestQueue, FrameClient, TrafficSaving
from app.robot.telemetry import (
    METRICS_TOPIC,
    LidarMetrics,
    MetricsItem,
    TelemetryClient,
    envelope,
    to_json_safe,
)
from app.robot.unitree import RTC_TOPIC, decode_points, install_raw_lidar_decoder

__all__ = [
    "FRAME_HEADER",
    "HEADER_LEN",
    "LIDAR_TOPIC",
    "ClientMessage",
    "LidarClient",
    "LidarStream",
    "RawLidarMessage",
    "TelemetryClient",
    "build_frame",
    "to_json_safe",
]

log = logging.getLogger(__name__)

LIDAR_TOPIC = RTC_TOPIC["ULIDAR_ARRAY"]
EXTRA_TOPICS = {
    RTC_TOPIC["ROBOTODOM"]: "lidar_pose",
    RTC_TOPIC["ULIDAR_STATE"]: "lidar_state",
}
"""Tópico do robô → `topic` em `/ws/telemetry` (F-002)."""

FRAME_VERSION = 1
FRAME_HEADER = struct.Struct("<BBHIdIf3fI")
"""version, flags, header_len, seq, ts, n_points, resolution, origin[3], reserved."""
HEADER_LEN = FRAME_HEADER.size

CLOSE_UNAVAILABLE = (1011, "lidar_unavailable")
CLOSE_SHUTDOWN = (1001, "shutdown")
ACTIVATION_FAILED = "activation_failed"
TRAFFIC_HOLDER = "lidar"
"""Dono do LiDAR/telemetria no refcount comum de `disableTrafficSaving`."""

PointDecoder = Callable[[bytes, int, Sequence[float], float], NDArray[np.float64]]
"""`(payload, src_size, origin, resolution) -> pontos (N, 3)`."""


@dataclass(frozen=True)
class RawLidarMessage:
    """Mensagem de LiDAR como chegou do robô, ainda comprimida."""

    seq: int
    ts: float
    payload: bytes
    src_size: int
    origin: tuple[float, ...]
    resolution: float
    arrival: float = 0.0
    """Relógio monotônico no callback; base do `pipeline_ms`."""


def build_frame(message: RawLidarMessage, decode: PointDecoder) -> bytes:
    """Decodifica e monta o frame binário v1. Roda na thread do worker."""
    points = decode(
        message.payload, message.src_size, message.origin, message.resolution
    )
    body = np.ascontiguousarray(points, dtype="<f4").reshape(-1, 3)
    header = FRAME_HEADER.pack(
        FRAME_VERSION,
        0,
        HEADER_LEN,
        message.seq & 0xFFFFFFFF,
        message.ts,
        len(body),
        message.resolution,
        *message.origin,
        0,
    )
    return header + body.tobytes()


def _timed_build(
    message: RawLidarMessage, decode: PointDecoder
) -> tuple[bytes, float, float]:
    """`build_frame` com o tempo gasto e o instante do fim, na thread do worker."""
    start = time.perf_counter()
    frame = build_frame(message, decode)
    return frame, time.perf_counter() - start, time.monotonic()


def _parse(
    seq: int, ts: float, arrival: float, message: dict[str, Any]
) -> RawLidarMessage:
    """Extrai os campos do callback.

    Raises:
        KeyError, TypeError, ValueError: se a mensagem vier malformada.
    """
    data = message["data"]
    origin = tuple(float(v) for v in data["origin"])
    if len(origin) != 3:  # noqa: PLR2004 - x, y, z
        msg = f"origin com {len(origin)} valores"
        raise ValueError(msg)
    payload = data["data"]
    if not isinstance(payload, bytes | bytearray):
        msg = "payload não é binário: o decoder de repasse está instalado?"
        raise TypeError(msg)
    return RawLidarMessage(
        seq=seq,
        ts=ts,
        payload=bytes(payload),
        src_size=int(data["src_size"]),
        origin=origin,
        resolution=float(data["resolution"]),
        arrival=arrival,
    )


class LidarClient(FrameClient):
    """Saída de um cliente do `/ws/lidar` (ver :class:`FrameClient`)."""


class LidarStream:
    """Liga o LiDAR do robô aos clientes de `/ws/lidar` e `/ws/telemetry`."""

    def __init__(  # noqa: PLR0913 - configuração explícita, sem objeto extra
        self,
        link: RobotLink,
        *,
        max_clients: int,
        client_queue: int,
        decode_queue: int,
        request_timeout_s: float,
        telemetry_max_clients: int = 1,
        telemetry_queue: int = 16,
        metrics_interval_s: float | None = 1.0,
        decoder: PointDecoder = decode_points,
        clock: Callable[[], float] = time.time,
        monotonic: Callable[[], float] = time.monotonic,
        traffic: TrafficSaving | None = None,
    ) -> None:
        """Recebe a conexão e os limites; ouve as transições da conexão.

        Args:
            link: Conexão com o robô.
            max_clients: Limite de `/ws/lidar`.
            client_queue: Frames à espera por cliente de `/ws/lidar`.
            decode_queue: Mensagens à espera do decoder.
            request_timeout_s: Teto do `disableTrafficSaving`.
            telemetry_max_clients: Limite de `/ws/telemetry`.
            telemetry_queue: Itens por tópico por cliente de telemetria.
            metrics_interval_s: Janela do `lidar_metrics`; `None` desliga o
                relógio (os testes chamam :meth:`emit_metrics`).
            decoder: Voxel map → pontos.
            clock: Relógio de parede (`ts` dos frames).
            monotonic: Relógio monotônico (intervalos e janela).
            traffic: Refcount de `disableTrafficSaving` comum aos streams
                (F-003); o padrão é um só deste stream.
        """
        self._link = link
        self._max_clients = max_clients
        self._client_queue = client_queue
        self._traffic = traffic or TrafficSaving(request_timeout_s)
        self._telemetry_max_clients = telemetry_max_clients
        self._telemetry_queue = telemetry_queue
        self._metrics_interval_s = metrics_interval_s
        self._decoder = decoder
        self._clock = clock
        self._monotonic = monotonic
        self._clients: list[LidarClient] = []
        self._telemetry: list[TelemetryClient] = []
        self._input: DropOldestQueue[RawLidarMessage] = DropOldestQueue(decode_queue)
        self._seq = 0
        self._active_channel: DataChannel | None = None
        self._extras_channel: DataChannel | None = None
        self._failed = False
        self._last_error: str | None = None
        self._metrics = LidarMetrics(window_start=monotonic())
        self._decoded_total = 0
        self._decode_errors_total = 0
        self._sync_task: asyncio.Task[None] | None = None
        self._worker: asyncio.Task[None] | None = None
        self._ticker: asyncio.Task[None] | None = None
        self._executor: ThreadPoolExecutor | None = None
        link.state.subscribe(self.on_connection)

    # ─── Ciclo de vida ─────────────────────────────────────────────────────

    def start(self) -> None:
        """Sobe o worker de decodificação (uma thread, em ordem)."""
        if self._worker is not None:
            return
        self._executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="lidar-decode"
        )
        self._worker = asyncio.create_task(self._run_worker())

    async def stop(self) -> None:
        """Fecha os clientes e para o worker, o relógio e a ativação pendente."""
        for client in self._clients:
            client.close(*CLOSE_SHUTDOWN)
        for telemetry in self._telemetry:
            telemetry.close(*CLOSE_SHUTDOWN)
        self._clients.clear()
        self._telemetry.clear()
        for task in (self._sync_task, self._worker, self._ticker):
            if task is not None and not task.done():
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
        self._sync_task = self._worker = self._ticker = None
        if self._executor is not None:
            self._executor.shutdown(wait=True, cancel_futures=True)
            self._executor = None

    async def wait_idle(self) -> None:
        """Espera a ativação/desativação em curso terminar."""
        while self._sync_task is not None and not self._sync_task.done():
            await asyncio.shield(self._sync_task)

    # ─── Clientes ──────────────────────────────────────────────────────────

    def add_client(self) -> LidarClient | None:
        """Registra um cliente de `/ws/lidar`; `None` se o limite foi atingido."""
        if len(self._clients) >= self._max_clients:
            return None
        client = LidarClient(self._client_queue)
        client.push_text(self._connection_text(self._link.state.current.state))
        self._clients.append(client)
        self._failed = False  # cliente novo pode tentar de novo (F-001)
        self._schedule_sync()
        return client

    def remove_client(self, client: LidarClient) -> None:
        """Tira o cliente de `/ws/lidar` e reavalia a ativação."""
        if client in self._clients:
            self._clients.remove(client)
        self._schedule_sync()

    def add_telemetry_client(self) -> TelemetryClient | None:
        """Registra um cliente de `/ws/telemetry`; `None` se o limite foi atingido."""
        if len(self._telemetry) >= self._telemetry_max_clients:
            return None
        client = TelemetryClient(self._telemetry_queue)
        client.push_connection(self._connection_text(self._link.state.current.state))
        if not self._telemetry:
            self._start_window()
        self._telemetry.append(client)
        self._failed = False
        self._schedule_sync()
        return client

    def remove_telemetry_client(self, client: TelemetryClient) -> None:
        """Tira o cliente de telemetria e reavalia as assinaturas."""
        if client in self._telemetry:
            self._telemetry.remove(client)
        if not self._telemetry and self._ticker is not None:
            self._ticker.cancel()
            self._ticker = None
        self._schedule_sync()

    def pending_decode_count(self) -> int:
        """Mensagens esperando o decoder."""
        return len(self._input)

    def decoded_total(self) -> int:
        """Decodificações concluídas desde a criação (diagnóstico e testes)."""
        return self._decoded_total

    def decode_errors_total(self) -> int:
        """Falhas de decodificação desde a criação (diagnóstico e testes)."""
        return self._decode_errors_total

    # ─── Conexão ───────────────────────────────────────────────────────────

    def on_connection(self, payload: dict[str, str]) -> None:
        """Repassa a transição aos clientes e reavalia a ativação."""
        state = ConnectionState(payload["state"])
        text = self._connection_text(state)
        for client in self._clients:
            client.push_text(text)
        for telemetry in self._telemetry:
            telemetry.push_connection(text)
        if state is not ConnectionState.connected:
            # As assinaturas morreram com a conexão: nada a cancelar no robô.
            self._active_channel = None
            self._extras_channel = None
            self._input.clear()
            self._traffic.forget(TRAFFIC_HOLDER)
            self._traffic.on_disconnect()
        self._metrics.reset_interval()
        self._schedule_sync()

    def _connection_text(self, state: ConnectionState) -> str:
        return json.dumps(
            {"topic": "connection", "ts": self._clock(), "data": {"state": state.value}}
        )

    def _robot_ready(self) -> bool:
        return (
            self._link.is_connected
            and self._link.state.current.state is ConnectionState.connected
        )

    # ─── Ativação (refcount) ───────────────────────────────────────────────

    def _schedule_sync(self) -> None:
        if self._sync_task is None or self._sync_task.done():
            self._sync_task = asyncio.create_task(self._sync())

    async def _sync(self) -> None:
        """Ativa ou desativa até o estado bater com clientes × conexão."""
        while True:
            channel = self._link.datachannel if self._robot_ready() else None
            lidar_on = channel is not None and channel is self._active_channel
            extras_on = channel is not None and channel is self._extras_channel
            any_client = bool(self._clients or self._telemetry)
            if channel is not None and any_client and not self._failed and not lidar_on:
                await self._activate(channel)
            elif lidar_on and self._telemetry and not extras_on:
                assert channel is not None  # noqa: S101 - garantido por lidar_on
                self._subscribe_extras(channel)
            elif self._extras_channel is not None and not self._telemetry:
                self._unsubscribe_extras(self._extras_channel)
            elif self._active_channel is not None and not any_client:
                await self._deactivate(self._active_channel)
            else:
                return

    async def _activate(self, channel: DataChannel) -> None:
        install_raw_lidar_decoder(channel)
        ok = await self._traffic.acquire(TRAFFIC_HOLDER, channel)
        if not ok:
            log.error("❌ LiDAR indisponível: disableTrafficSaving falhou.")
            self._failed = True
            self._last_error = ACTIVATION_FAILED
            for client in self._clients:
                client.close(*CLOSE_UNAVAILABLE)
            self._clients.clear()
            return
        if channel is not self._link.datachannel or not self._robot_ready():
            self._traffic.forget(TRAFFIC_HOLDER)
            return  # a conexão mudou durante a espera; o laço reavalia
        channel.pub_sub.subscribe(LIDAR_TOPIC, self._on_message)
        self._active_channel = channel
        self._last_error = None
        log.info("LiDAR ativado.")

    async def _deactivate(self, channel: DataChannel) -> None:
        self._active_channel = None
        self._input.clear()
        self._metrics.reset_interval()
        self._unsubscribe(channel, LIDAR_TOPIC)
        await self._traffic.release(TRAFFIC_HOLDER, channel)
        log.info("LiDAR desativado.")

    def _subscribe_extras(self, channel: DataChannel) -> None:
        for topic, name in EXTRA_TOPICS.items():
            channel.pub_sub.subscribe(topic, self._extra_callback(name))
        self._extras_channel = channel

    def _unsubscribe_extras(self, channel: DataChannel) -> None:
        self._extras_channel = None
        for topic in EXTRA_TOPICS:
            self._unsubscribe(channel, topic)

    @staticmethod
    def _unsubscribe(channel: DataChannel, topic: str) -> None:
        channel.pub_sub.unsubscribe(topic)
        # A lib não remove o callback no unsubscribe (pegadinha #2).
        channel.pub_sub.subscriptions.pop(topic, None)

    # ─── Dados ─────────────────────────────────────────────────────────────

    def _on_message(self, message: dict[str, Any]) -> None:
        """Callback do LiDAR, no loop: só numera, conta, valida e enfileira."""
        seq, self._seq = self._seq, (self._seq + 1) & 0xFFFFFFFF
        arrival = self._monotonic()
        self._metrics.on_received(seq, arrival)
        try:
            raw = _parse(seq, self._clock(), arrival, message)
        except (KeyError, TypeError, ValueError):
            self._metrics.malformed += 1
            log.warning("❌ Mensagem de LiDAR malformada descartada (seq %d).", seq)
            return
        self._metrics.on_valid(
            len(raw.payload), raw.src_size, raw.resolution, raw.origin
        )
        if self._input.put(raw):
            self._metrics.dropped_decode_queue += 1

    def _extra_callback(self, name: str) -> Callable[[dict[str, Any]], None]:
        def on_extra(message: dict[str, Any]) -> None:
            """Converte uma vez e entrega o mesmo texto a todos os clientes."""
            text = envelope(name, self._clock(), message.get("data"))
            for telemetry in self._telemetry:
                telemetry.push(name, text)

        return on_extra

    async def _run_worker(self) -> None:
        loop = asyncio.get_running_loop()
        while True:
            raw = await self._input.get()
            try:
                frame, decode_s, done = await loop.run_in_executor(
                    self._executor, _timed_build, raw, self._decoder
                )
            except Exception:
                self._metrics.decode_errors += 1
                self._decode_errors_total += 1
                log.exception("❌ Falha ao decodificar LiDAR (seq %d).", raw.seq)
                continue
            n_points = (len(frame) - HEADER_LEN) // 12
            pipeline_s = max(done - raw.arrival, 0.0) if raw.arrival else 0.0
            self._metrics.on_decoded(n_points, decode_s * 1000, pipeline_s * 1000)
            self._decoded_total += 1
            for client in self._clients:
                if client.push_frame(frame):
                    self._metrics.dropped_lidar_clients += 1

    # ─── Métricas ──────────────────────────────────────────────────────────

    def _start_window(self) -> None:
        last = self._metrics.last_arrival
        self._metrics = LidarMetrics(window_start=self._monotonic())
        self._metrics.last_arrival = last
        if self._metrics_interval_s is not None and self._ticker is None:
            self._ticker = asyncio.create_task(self._tick(self._metrics_interval_s))

    async def _tick(self, interval_s: float) -> None:
        while True:
            await asyncio.sleep(interval_s)
            self.emit_metrics()

    def emit_metrics(self) -> None:
        """Fecha a janela e entrega o `lidar_metrics` aos clientes de telemetria."""
        now = self._monotonic()
        summary = self._metrics.close_window(
            now,
            active=self._active_channel is not None,
            last_error=self._last_error,
            lidar_clients=len(self._clients),
            telemetry_clients=len(self._telemetry),
        )
        last = self._metrics.last_arrival
        self._metrics = LidarMetrics(window_start=now)
        self._metrics.last_arrival = last
        item = MetricsItem(ts=self._clock(), data=summary)
        for telemetry in self._telemetry:
            telemetry.push(METRICS_TOPIC, item)
