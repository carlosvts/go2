"""Câmera frontal do robô para o stream `/ws/video` (F-003).

Fluxo dos dados:

```
track do aiortc (loop) ─▶ leitura contínua: todo quadro é lido
   ─▶ teto de taxa ─▶ fila do codificador (descarta o mais antigo)
   ─▶ worker único (thread) converte e codifica em JPEG
   ─▶ fila de cada cliente de /ws/video (descarta o mais antigo)
```

Refcount: a câmera fica ligada (`switchVideoChannel(True)`) enquanto há
cliente e conexão; o `disableTrafficSaving` é comum com o LiDAR
(:class:`~app.robot.streams.TrafficSaving`). Ativar e desativar passam por
uma única tarefa, que reavalia o estado até ele estabilizar, como no LiDAR.
"""

import asyncio
import contextlib
import json
import logging
import math
import struct
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

import cv2

from app.robot.connection import ConnectionState
from app.robot.link import RobotLink
from app.robot.ports import DataChannel, VideoFrame, VideoTrack
from app.robot.streams import DropOldestQueue, FrameClient, TrafficSaving, state_text

__all__ = [
    "HEADER_LEN",
    "VIDEO_HEADER",
    "VideoClient",
    "VideoState",
    "VideoStream",
    "encode_frame",
]

log = logging.getLogger(__name__)

FRAME_VERSION = 1
VIDEO_HEADER = struct.Struct("<BBHIdHHId")
"""version, flags, header_len, seq, ts, width, height, jpeg_len, media_time."""
HEADER_LEN = VIDEO_HEADER.size

CLOSE_UNAVAILABLE = (1011, "video_unavailable")
CLOSE_SHUTDOWN = (1001, "shutdown")
TRAFFIC_HOLDER = "video"
"""Dono do vídeo no refcount comum de `disableTrafficSaving`."""

FrameEncoder = Callable[[VideoFrame, int, float, int], bytes]
"""`(quadro, seq, ts, qualidade) -> frame binário v1`. Roda fora do loop."""


class VideoState(StrEnum):
    """Estado do stream enviado no tópico `video`."""

    starting = "starting"
    streaming = "streaming"
    stalled = "stalled"


class VideoClient(FrameClient):
    """Saída de um cliente do `/ws/video` (ver :class:`FrameClient`)."""


def encode_frame(frame: VideoFrame, seq: int, ts: float, quality: int) -> bytes:
    """Converte o quadro, codifica em JPEG e monta o frame v1. Fora do loop.

    Raises:
        ValueError: se o OpenCV não conseguir codificar.
    """
    image = frame.to_ndarray(format="bgr24")
    ok, jpeg = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, quality])
    if not ok:
        msg = "cv2.imencode falhou"
        raise ValueError(msg)
    body = jpeg.tobytes()
    media_time = frame.time
    header = VIDEO_HEADER.pack(
        FRAME_VERSION,
        0,
        HEADER_LEN,
        seq & 0xFFFFFFFF,
        ts,
        frame.width,
        frame.height,
        len(body),
        math.nan if media_time is None else float(media_time),
    )
    return header + body


@dataclass(frozen=True)
class _Admitted:
    """Quadro admitido, à espera do codificador."""

    seq: int
    ts: float
    frame: VideoFrame
    generation: int


@dataclass
class _Counters:
    """Contadores de uma janela (ou dos totais) do `video_metrics`."""

    read: int = 0
    admitted: int = 0
    dropped_rate: int = 0
    dropped_encode_queue: int = 0
    encode_errors: int = 0
    encoded: int = 0
    dropped_clients: dict[int, int] = field(default_factory=dict)

    def as_dict(self, clients: list[VideoClient]) -> dict[str, Any]:
        return {
            "read": self.read,
            "admitted": self.admitted,
            "dropped_rate": self.dropped_rate,
            "dropped_encode_queue": self.dropped_encode_queue,
            "encode_errors": self.encode_errors,
            "encoded": self.encoded,
            "dropped_clients": [self.dropped_clients.get(id(c), 0) for c in clients],
        }


class VideoStream:
    """Liga a câmera do robô aos clientes de `/ws/video`."""

    def __init__(  # noqa: PLR0913 - configuração explícita, sem objeto extra
        self,
        link: RobotLink,
        *,
        traffic: TrafficSaving,
        max_clients: int,
        client_queue: int,
        encode_queue: int,
        max_fps: float,
        jpeg_quality: int,
        stall_s: float,
        metrics_interval_s: float | None = 1.0,
        stall_check_s: float | None = 0.25,
        encoder: FrameEncoder = encode_frame,
        clock: Callable[[], float] = time.time,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        """Recebe a conexão e os limites; ouve a conexão e a track de vídeo.

        Args:
            link: Conexão com o robô.
            traffic: Refcount de `disableTrafficSaving` comum aos streams.
            max_clients: Limite de `/ws/video`.
            client_queue: Frames à espera por cliente.
            encode_queue: Quadros à espera do codificador.
            max_fps: Teto de quadros admitidos por segundo; `0` = sem teto.
            jpeg_quality: Qualidade do JPEG (1–100).
            stall_s: Segundos sem quadro até o estado `stalled`.
            metrics_interval_s: Janela do `video_metrics` no log; `None`
                desliga o relógio (os testes chamam :meth:`emit_metrics`).
            stall_check_s: Período da verificação de `stalled`; `None`
                desliga (os testes chamam :meth:`check_stall`).
            encoder: Quadro → frame binário.
            clock: Relógio de parede (`ts` dos frames e textos).
            monotonic: Relógio monotônico (teto de taxa e `stalled`).
        """
        self._link = link
        self._traffic = traffic
        self._max_clients = max_clients
        self._client_queue = client_queue
        self._min_interval_s = 1.0 / max_fps if max_fps > 0 else 0.0
        self._jpeg_quality = jpeg_quality
        self._stall_s = stall_s
        self._metrics_interval_s = metrics_interval_s
        self._stall_check_s = stall_check_s
        self._encoder = encoder
        self._clock = clock
        self._monotonic = monotonic
        self._clients: list[VideoClient] = []
        self._input: DropOldestQueue[_Admitted] = DropOldestQueue(encode_queue)
        self._seq = 0
        self._active_channel: DataChannel | None = None
        self._failed = False
        self._generation = 0
        self._state: VideoState | None = None
        self._last_read = monotonic()
        self._last_admit: float | None = None
        self._read_this_connection = 0
        self._window = _Counters()
        self._totals = _Counters()
        self._reader: asyncio.Task[None] | None = None
        self._sync_task: asyncio.Task[None] | None = None
        self._worker: asyncio.Task[None] | None = None
        self._ticker: asyncio.Task[None] | None = None
        self._staller: asyncio.Task[None] | None = None
        self._executor: ThreadPoolExecutor | None = None
        link.state.subscribe(self.on_connection)
        link.subscribe_video_track(self.on_track)

    # ─── Ciclo de vida ─────────────────────────────────────────────────────

    def start(self) -> None:
        """Sobe o worker de codificação (uma thread, em ordem) e os relógios."""
        if self._worker is not None:
            return
        self._executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="video-encode"
        )
        self._worker = asyncio.create_task(self._run_worker())
        if self._metrics_interval_s is not None:
            self._ticker = asyncio.create_task(self._tick(self._metrics_interval_s))
        if self._stall_check_s is not None:
            self._staller = asyncio.create_task(self._watch(self._stall_check_s))

    async def stop(self) -> None:
        """Fecha os clientes e para leitura, worker, relógios e ativação."""
        for client in self._clients:
            client.close(*CLOSE_SHUTDOWN)
        self._clients.clear()
        tasks = (self._sync_task, self._worker, self._ticker, self._staller)
        for task in (*tasks, self._reader):
            if task is not None and not task.done():
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
        self._sync_task = self._worker = self._ticker = self._staller = None
        self._reader = None
        if self._executor is not None:
            self._executor.shutdown(wait=True, cancel_futures=True)
            self._executor = None

    async def wait_idle(self) -> None:
        """Espera a ativação/desativação em curso terminar."""
        while self._sync_task is not None and not self._sync_task.done():
            await asyncio.shield(self._sync_task)

    # ─── Clientes ──────────────────────────────────────────────────────────

    def add_client(self) -> VideoClient | None:
        """Registra um cliente de `/ws/video`; `None` se o limite foi atingido."""
        if len(self._clients) >= self._max_clients:
            return None
        client = VideoClient(self._client_queue)
        client.push_text(self._connection_text(self._link.state.current.state))
        if self._active_channel is not None and self._state is not None:
            client.push_text(state_text("video", self._clock(), self._state.value))
        self._clients.append(client)
        self._failed = False  # cliente novo pode tentar de novo (F-003)
        self._schedule_sync()
        return client

    def remove_client(self, client: VideoClient) -> None:
        """Tira o cliente e reavalia a ativação."""
        if client in self._clients:
            self._clients.remove(client)
        self._window.dropped_clients.pop(id(client), None)
        self._schedule_sync()

    # ─── Diagnóstico ───────────────────────────────────────────────────────

    def reader_count(self) -> int:
        """Leitores de track ativos (0 ou 1)."""
        return int(self._reader is not None and not self._reader.done())

    def pending_encode_count(self) -> int:
        """Quadros esperando o codificador."""
        return len(self._input)

    def read_total(self) -> int:
        """Quadros lidos da track desde a criação."""
        return self._totals.read

    def admitted_total(self) -> int:
        """Quadros admitidos (receberam `seq`) desde a criação."""
        return self._totals.admitted

    def encoded_total(self) -> int:
        """Frames codificados e entregues às filas dos clientes."""
        return self._totals.encoded

    def encode_errors_total(self) -> int:
        """Quadros pulados por erro de conversão ou codificação."""
        return self._totals.encode_errors

    def metrics_totals(self) -> dict[str, Any]:
        """Totais desde a criação, no formato do `video_metrics`."""
        return self._totals.as_dict(self._clients)

    # ─── Conexão ───────────────────────────────────────────────────────────

    def on_connection(self, payload: dict[str, str]) -> None:
        """Repassa a transição aos clientes e reavalia a ativação."""
        state = ConnectionState(payload["state"])
        text = self._connection_text(state)
        for client in self._clients:
            client.push_text(text)
        if state is not ConnectionState.connected:
            # A câmera morreu com a conexão: nada a desligar no robô.
            self._mark_inactive()
            self._traffic.forget(TRAFFIC_HOLDER)
            self._traffic.on_disconnect()
        self._schedule_sync()

    def on_track(self, track: VideoTrack) -> None:
        """Nova track (nova conexão): troca o leitor, um só por vez."""
        if self._reader is not None and not self._reader.done():
            self._reader.cancel()
        self._read_this_connection = 0
        self._reader = asyncio.create_task(self._read(track))

    def _connection_text(self, state: ConnectionState) -> str:
        return state_text("connection", self._clock(), state.value)

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
            active = channel is not None and channel is self._active_channel
            if (
                channel is not None
                and self._clients
                and not self._failed
                and not active
            ):
                await self._activate(channel)
            elif self._active_channel is not None and not self._clients:
                await self._deactivate(self._active_channel)
            else:
                return

    async def _activate(self, channel: DataChannel) -> None:
        if not await self._traffic.acquire(TRAFFIC_HOLDER, channel):
            log.error("❌ Vídeo indisponível: disableTrafficSaving falhou.")
            self._fail()
            return
        if channel is not self._link.datachannel or not self._robot_ready():
            self._traffic.forget(TRAFFIC_HOLDER)
            return  # a conexão mudou durante a espera; o laço reavalia
        if not self._clients:
            await self._traffic.release(TRAFFIC_HOLDER, channel)
            return
        try:
            channel.switchVideoChannel(True)
        except Exception:
            log.exception("❌ Vídeo indisponível: switchVideoChannel(True) falhou.")
            await self._traffic.release(TRAFFIC_HOLDER, channel)
            self._fail()
            return
        self._active_channel = channel
        self._generation += 1
        self._last_read = self._monotonic()
        self._last_admit = None
        self._set_state(VideoState.starting)
        log.info("Câmera ligada.")

    async def _deactivate(self, channel: DataChannel) -> None:
        self._mark_inactive()
        try:
            channel.switchVideoChannel(False)
        except Exception:
            log.exception("❌ switchVideoChannel(False) falhou (sem cliente).")
        await self._traffic.release(TRAFFIC_HOLDER, channel)
        log.info("Câmera desligada.")

    def _mark_inactive(self) -> None:
        self._active_channel = None
        self._generation += 1
        self._input.clear()
        self._state = None

    def _fail(self) -> None:
        self._failed = True
        for client in self._clients:
            client.close(*CLOSE_UNAVAILABLE)
        self._clients.clear()

    def _set_state(self, state: VideoState) -> None:
        self._state = state
        text = state_text("video", self._clock(), state.value)
        for client in self._clients:
            client.push_text(text)

    # ─── Dados ─────────────────────────────────────────────────────────────

    async def _read(self, track: VideoTrack) -> None:
        """Lê todo quadro da track, com ou sem cliente: a fila dela não tem limite."""
        while True:
            try:
                frame = await track.recv()
            except Exception as exc:
                log.info("Track de vídeo terminou (%s).", type(exc).__name__)
                return
            self._on_frame(frame)

    def _on_frame(self, frame: VideoFrame) -> None:
        """No loop: conta, aplica o teto, numera e enfileira."""
        now = self._monotonic()
        self._window.read += 1
        self._totals.read += 1
        self._read_this_connection += 1
        self._last_read = now
        if self._active_channel is None or not self._clients:
            return
        if (
            self._last_admit is not None
            and now - self._last_admit < self._min_interval_s
        ):
            self._window.dropped_rate += 1
            self._totals.dropped_rate += 1
            return
        self._last_admit = now
        seq, self._seq = self._seq, (self._seq + 1) & 0xFFFFFFFF
        self._window.admitted += 1
        self._totals.admitted += 1
        item = _Admitted(seq, self._clock(), frame, self._generation)
        if self._input.put(item):
            self._window.dropped_encode_queue += 1
            self._totals.dropped_encode_queue += 1
        if self._state is not VideoState.streaming:
            self._set_state(VideoState.streaming)

    async def _run_worker(self) -> None:
        loop = asyncio.get_running_loop()
        while True:
            item = await self._input.get()
            try:
                data = await loop.run_in_executor(
                    self._executor,
                    self._encoder,
                    item.frame,
                    item.seq,
                    item.ts,
                    self._jpeg_quality,
                )
            except Exception:
                self._window.encode_errors += 1
                self._totals.encode_errors += 1
                log.exception(
                    "❌ Falha ao codificar quadro de vídeo (seq %d).", item.seq
                )
                continue
            if item.generation != self._generation or self._active_channel is None:
                continue  # a câmera foi desligada enquanto o quadro codificava
            self._window.encoded += 1
            self._totals.encoded += 1
            for client in self._clients:
                if client.push_frame(data):
                    key = id(client)
                    self._window.dropped_clients[key] = (
                        self._window.dropped_clients.get(key, 0) + 1
                    )

    # ─── `stalled` e métricas ──────────────────────────────────────────────

    def check_stall(self) -> None:
        """Passa a `stalled` se a câmera ativa ficou `stall_s` sem quadro."""
        if self._active_channel is None or self._state is VideoState.stalled:
            return
        if self._monotonic() - self._last_read < self._stall_s:
            return
        self._set_state(VideoState.stalled)
        log.warning(
            "❌ Câmera ligada sem quadros há %.1f s (%d lidos nesta conexão).",
            self._stall_s,
            self._read_this_connection,
        )

    async def _watch(self, interval_s: float) -> None:
        while True:
            await asyncio.sleep(interval_s)
            self.check_stall()

    def emit_metrics(self) -> dict[str, Any]:
        """Fecha a janela, registra `video_metrics` (INFO) e devolve o resumo."""
        summary = self._window.as_dict(self._clients)
        self._window = _Counters()
        log.info("video_metrics %s", json.dumps(summary))
        return summary

    async def _tick(self, interval_s: float) -> None:
        while True:
            await asyncio.sleep(interval_s)
            if self.reader_count():
                self.emit_metrics()
