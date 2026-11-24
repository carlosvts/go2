"""Peças comuns aos streams de WebSocket (`/ws/lidar`, `/ws/telemetry`, `/ws/video`).

- :class:`DropOldestQueue`: fila limitada que, cheia, descarta o mais antigo.
- :class:`FrameClient`: saída de um cliente de frames binários.
- :class:`TrafficSaving`: refcount comum do `disableTrafficSaving` (F-003).
"""

import asyncio
import json
import logging
from collections import deque

from app.robot.clients import ClientMessage
from app.robot.ports import DataChannel

log = logging.getLogger(__name__)


def state_text(topic: str, ts: float, state: str) -> str:
    """Frame de texto `{"topic", "ts", "data": {"state"}}`."""
    return json.dumps({"topic": topic, "ts": ts, "data": {"state": state}})


class DropOldestQueue[T]:
    """Fila limitada para um consumidor: cheia, descarta o item mais antigo."""

    def __init__(self, maxsize: int) -> None:
        """Cria a fila com espaço para `maxsize` itens."""
        self._items: deque[T] = deque(maxlen=maxsize)
        self._ready = asyncio.Event()

    def put(self, item: T) -> bool:
        """Enfileira; devolve `True` se descartou um item para caber."""
        dropped = len(self._items) == self._items.maxlen
        self._items.append(item)
        self._ready.set()
        return dropped

    async def get(self) -> T:
        """Espera e retira o item mais antigo."""
        while not self._items:
            self._ready.clear()
            await self._ready.wait()
        return self._items.popleft()

    def clear(self) -> None:
        """Descarta tudo o que está na fila."""
        self._items.clear()

    def __len__(self) -> int:
        """Itens na fila."""
        return len(self._items)


class FrameClient:
    """Saída de um cliente de frames binários.

    Prioridade: frames de texto (estado, nunca descartados) > fechamento >
    frames binários (fila curta, descarta o mais antigo).
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

    def push_frame(self, frame: bytes) -> bool:
        """Enfileira um frame binário; devolve `True` se descartou um antigo."""
        if self._close is not None:
            return False
        dropped = len(self._frames) == self._frames.maxlen
        self._frames.append(frame)
        self._ready.set()
        return dropped

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

    def drain_messages(self) -> list[ClientMessage]:
        """Retira tudo o que está pronto, sem esperar (testes e diagnóstico)."""
        messages: list[ClientMessage] = [ClientMessage("text", t) for t in self._texts]
        self._texts.clear()
        if self._close is not None:
            code, reason = self._close
            messages.append(ClientMessage("close", code=code, reason=reason))
        messages += [ClientMessage("bytes", f) for f in self._frames]
        self._frames.clear()
        return messages

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


class TrafficSaving:
    """Refcount comum do `disableTrafficSaving` (F-003).

    LiDAR/telemetria e vídeo usam o mesmo data channel. `True` vai ao robô
    quando o primeiro *dono* pede num canal; `False`, quando o último dono
    solta. As chamadas são serializadas por um lock, e cada uma tem timeout.
    """

    def __init__(self, request_timeout_s: float) -> None:
        """Recebe o teto de cada chamada ao robô."""
        self._request_timeout_s = request_timeout_s
        self._holders: set[str] = set()
        self._channel: DataChannel | None = None
        self._lock = asyncio.Lock()

    @property
    def holders(self) -> frozenset[str]:
        """Donos atuais (diagnóstico e testes)."""
        return frozenset(self._holders)

    async def acquire(self, holder: str, channel: DataChannel) -> bool:
        """Garante o `True` em `channel` para `holder`; `False` se falhou.

        Se outro dono já ligou neste mesmo canal, não chama o robô de novo.
        Na falha, `holder` não fica registrado.
        """
        async with self._lock:
            if self._channel is channel:
                self._holders.add(holder)
                return True
            if not await self._call(channel, switch=True):
                self._holders.discard(holder)
                return False
            self._channel = channel
            self._holders.add(holder)
            return True

    async def release(self, holder: str, channel: DataChannel | None) -> None:
        """Solta `holder`; sem donos, desfaz o `True` em `channel`.

        Com `channel` diferente do canal ligado (ou `None`), só esquece o
        dono: a conexão em que o `True` valia já morreu.
        """
        async with self._lock:
            self._holders.discard(holder)
            if self._holders or channel is None or channel is not self._channel:
                return
            self._channel = None
            if not await self._call(channel, switch=False):
                log.warning("❌ Falha ao desfazer disableTrafficSaving (sem cliente).")

    def forget(self, holder: str) -> None:
        """Esquece `holder` sem falar com o robô (a conexão caiu)."""
        self._holders.discard(holder)
        if not self._holders:
            self._channel = None

    def on_disconnect(self) -> None:
        """A conexão caiu: o próximo `acquire` chama o robô de novo."""
        self._channel = None

    async def _call(self, channel: DataChannel, *, switch: bool) -> bool:
        try:
            return bool(
                await asyncio.wait_for(
                    channel.disableTrafficSaving(switch), self._request_timeout_s
                )
            )
        except Exception:
            log.exception("❌ disableTrafficSaving(%s) falhou.", switch)
            return False
