"""Stream de nuvem de pontos do LiDAR para clientes WebSocket (F-001).

Fluxo:

```
callback da lib (loop) ─▶ fila do decoder (descarta a mais antiga)
   ─▶ worker único (thread) decodifica e monta o frame
   ─▶ fila de cada cliente (descarta o mais antigo) ─▶ /ws/lidar
```

A assinatura no robô existe só enquanto há cliente e conexão (refcount).
Ativar e desativar passam por uma única tarefa, que reavalia o estado até
ele estabilizar: corridas entre clientes que chegam e saem e a conexão que
cai e volta se resolvem nela.
"""

import asyncio
import contextlib
import json
import logging
import struct
import time
from collections import deque
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Literal

import numpy as np
from numpy.typing import NDArray

from app.robot.connection import ConnectionState
from app.robot.link import RobotLink
from app.robot.ports import DataChannel
from app.robot.unitree import RTC_TOPIC, decode_points, install_raw_lidar_decoder

log = logging.getLogger(__name__)

LIDAR_TOPIC = RTC_TOPIC["ULIDAR_ARRAY"]

FRAME_VERSION = 1
FRAME_HEADER = struct.Struct("<BBHIdIf3fI")
"""version, flags, header_len, seq, ts, n_points, resolution, origin[3], reserved."""
HEADER_LEN = FRAME_HEADER.size

CLOSE_UNAVAILABLE = (1011, "lidar_unavailable")

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


def _parse(seq: int, ts: float, message: dict[str, Any]) -> RawLidarMessage:
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
    )


class _DropOldestQueue[T]:
    """Fila limitada para um consumidor: cheia, descarta o item mais antigo."""

    def __init__(self, maxsize: int) -> None:
        self._items: deque[T] = deque(maxlen=maxsize)
        self._ready = asyncio.Event()

    def put(self, item: T) -> None:
        self._items.append(item)
        self._ready.set()

    async def get(self) -> T:
        while not self._items:
            self._ready.clear()
            await self._ready.wait()
        return self._items.popleft()

    def clear(self) -> None:
        self._items.clear()

    def __len__(self) -> int:
        return len(self._items)


@dataclass(frozen=True)
class ClientMessage:
    """Próxima coisa a fazer com o WebSocket do cliente."""

    kind: Literal["bytes", "text", "close", "gone"]
    data: bytes | str | None = None
    code: int | None = None
    reason: str | None = None


class LidarClient:
    """Saída de um cliente do `/ws/lidar`.

    Prioridade: frames de texto (estado da conexão, nunca descartados) >
    fechamento > frames binários (fila curta, descarta o mais antigo).
    """

    def __init__(self, queue_size: int) -> None:
        """Cria a saída com a fila de frames binários de `queue_size`."""
        self._frames: deque[bytes] = deque(maxlen=queue_size)
        self._texts: deque[str] = deque()
        self._close: tuple[int, str] | None = None
        self._gone = False
        self._ready = asyncio.Event()

    @property
    def is_closed(self) -> bool:
        """A api decidiu fechar este cliente."""
        return self._close is not None

    def push_frame(self, frame: bytes) -> None:
        """Enfileira um frame binário (descarta o mais antigo se cheio)."""
        if self._close is None:
            self._frames.append(frame)
            self._ready.set()

    def push_text(self, text: str) -> None:
        """Enfileira um frame de texto; nunca é descartado."""
        self._texts.append(text)
        self._ready.set()

    def close(self, code: int, reason: str) -> None:
        """Pede o fechamento depois dos textos pendentes."""
        self._close = (code, reason)
        self._frames.clear()
        self._ready.set()

    def mark_gone(self) -> None:
        """O cliente desconectou por conta própria."""
        self._gone = True
        self._ready.set()

    def pending_texts(self) -> list[str]:
        """Retira e devolve os textos pendentes (uso em testes e diagnóstico)."""
        texts = list(self._texts)
        self._texts.clear()
        return texts

    def pending_frame_count(self) -> int:
        """Quantos frames binários esperam envio."""
        return len(self._frames)

    async def next(self) -> ClientMessage:
        """Espera a próxima mensagem a enviar ao cliente."""
        while True:
            if self._gone:
                return ClientMessage("gone")
            if self._texts:
                return ClientMessage("text", self._texts.popleft())
            if self._close is not None:
                code, reason = self._close
                return ClientMessage("close", code=code, reason=reason)
            if self._frames:
                return ClientMessage("bytes", self._frames.popleft())
            self._ready.clear()
            await self._ready.wait()


class LidarStream:
    """Liga o LiDAR do robô aos clientes WebSocket, com refcount."""

    def __init__(  # noqa: PLR0913 - configuração explícita, sem objeto extra
        self,
        link: RobotLink,
        *,
        max_clients: int,
        client_queue: int,
        decode_queue: int,
        request_timeout_s: float,
        decoder: PointDecoder = decode_points,
        clock: Callable[[], float] = time.time,
    ) -> None:
        """Recebe a conexão e os limites; ouve as transições da conexão."""
        self._link = link
        self._max_clients = max_clients
        self._client_queue = client_queue
        self._request_timeout_s = request_timeout_s
        self._decoder = decoder
        self._clock = clock
        self._clients: list[LidarClient] = []
        self._input: _DropOldestQueue[RawLidarMessage] = _DropOldestQueue(decode_queue)
        self._seq = 0
        self._active_channel: DataChannel | None = None
        self._sync_task: asyncio.Task[None] | None = None
        self._worker: asyncio.Task[None] | None = None
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
        """Fecha os clientes e para o worker e a ativação pendente."""
        for client in list(self._clients):
            client.close(1001, "shutdown")
        self._clients.clear()
        for task in (self._sync_task, self._worker):
            if task is not None and not task.done():
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
        self._sync_task = self._worker = None
        if self._executor is not None:
            self._executor.shutdown(wait=True, cancel_futures=True)
            self._executor = None

    async def wait_idle(self) -> None:
        """Espera a ativação/desativação em curso terminar."""
        while self._sync_task is not None and not self._sync_task.done():
            await asyncio.shield(self._sync_task)

    # ─── Clientes ──────────────────────────────────────────────────────────

    def add_client(self) -> LidarClient | None:
        """Registra um cliente; `None` se o limite já foi atingido."""
        if len(self._clients) >= self._max_clients:
            return None
        client = LidarClient(self._client_queue)
        client.push_text(self._connection_text(self._link.state.current.state))
        self._clients.append(client)
        self._schedule_sync()
        return client

    def remove_client(self, client: LidarClient) -> None:
        """Tira o cliente; o último a sair desativa o LiDAR no robô."""
        if client in self._clients:
            self._clients.remove(client)
        self._schedule_sync()

    def pending_decode_count(self) -> int:
        """Mensagens esperando o decoder."""
        return len(self._input)

    # ─── Conexão ───────────────────────────────────────────────────────────

    def on_connection(self, payload: dict[str, str]) -> None:
        """Repassa a transição aos clientes e reavalia a ativação."""
        state = ConnectionState(payload["state"])
        text = self._connection_text(state)
        for client in self._clients:
            client.push_text(text)
        if state is not ConnectionState.connected:
            # A assinatura morreu com a conexão: nada a cancelar no robô.
            self._active_channel = None
            self._input.clear()
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
            active = channel is not None and channel is self._active_channel
            if self._clients and channel is not None and not active:
                await self._activate(channel)
            elif not self._clients and self._active_channel is not None:
                await self._deactivate(self._active_channel)
            else:
                return

    async def _activate(self, channel: DataChannel) -> None:
        install_raw_lidar_decoder(channel)
        ok = await self._traffic_saving(channel, switch=True)
        if not ok:
            log.error("❌ LiDAR indisponível: disableTrafficSaving falhou.")
            for client in self._clients:
                client.close(*CLOSE_UNAVAILABLE)
            self._clients.clear()
            return
        if channel is not self._link.datachannel or not self._robot_ready():
            return  # a conexão mudou durante a espera; o laço reavalia
        channel.pub_sub.subscribe(LIDAR_TOPIC, self._on_message)
        self._active_channel = channel
        log.info("LiDAR ativado.")

    async def _deactivate(self, channel: DataChannel) -> None:
        self._active_channel = None
        self._input.clear()
        channel.pub_sub.unsubscribe(LIDAR_TOPIC)
        # A lib não remove o callback no unsubscribe (pegadinha #2).
        channel.pub_sub.subscriptions.pop(LIDAR_TOPIC, None)
        if not await self._traffic_saving(channel, switch=False):
            log.warning("❌ Falha ao desfazer disableTrafficSaving (sem cliente).")
        log.info("LiDAR desativado.")

    async def _traffic_saving(self, channel: DataChannel, *, switch: bool) -> bool:
        try:
            return bool(
                await asyncio.wait_for(
                    channel.disableTrafficSaving(switch), self._request_timeout_s
                )
            )
        except Exception:
            log.exception("❌ disableTrafficSaving(%s) falhou.", switch)
            return False

    # ─── Dados ─────────────────────────────────────────────────────────────

    def _on_message(self, message: dict[str, Any]) -> None:
        """Callback da lib, no loop: só numera, valida e enfileira."""
        seq, self._seq = self._seq, (self._seq + 1) & 0xFFFFFFFF
        try:
            raw = _parse(seq, self._clock(), message)
        except (KeyError, TypeError, ValueError):
            log.warning("❌ Mensagem de LiDAR malformada descartada (seq %d).", seq)
            return
        self._input.put(raw)

    async def _run_worker(self) -> None:
        loop = asyncio.get_running_loop()
        while True:
            raw = await self._input.get()
            try:
                frame = await loop.run_in_executor(
                    self._executor, build_frame, raw, self._decoder
                )
            except Exception:
                log.exception("❌ Falha ao decodificar LiDAR (seq %d).", raw.seq)
                continue
            for client in self._clients:
                client.push_frame(frame)
