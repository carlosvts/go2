"""Peças da telemetria do LiDAR (`/ws/telemetry`, F-002).

- :func:`to_json_safe`: converte dados crus do robô para JSON estrito.
- :class:`LidarMetrics`: acumula as métricas de uma janela.
- :class:`TelemetryClient`: saída de um cliente, com fila por tópico.

A orquestração (ativação, janela, worker) fica em :mod:`app.robot.lidar`.
"""

import asyncio
import base64
import json
import logging
import math
from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from app.robot.clients import ClientMessage

log = logging.getLogger(__name__)

METRICS_TOPIC = "lidar_metrics"


def to_json_safe(value: Any) -> Any:  # noqa: ANN401, PLR0911 - um caso por tipo
    """Converte recursivamente para algo que `json.dumps(allow_nan=False)` aceita.

    `bytes` → `{"base64"}`; NaN/±Inf → `{"nonfinite"}`; numpy → número/lista;
    chaves viram `str`; tuplas viram listas; o resto → `{"unserializable"}`.
    """
    if value is None or isinstance(value, str | bool | int):
        return value
    if isinstance(value, float):
        if math.isfinite(value):
            return value
        if math.isnan(value):
            return {"nonfinite": "nan"}
        return {"nonfinite": "inf" if value > 0 else "-inf"}
    if isinstance(value, bytes | bytearray):
        return {"base64": base64.b64encode(value).decode("ascii")}
    if isinstance(value, dict):
        return {str(key): to_json_safe(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [to_json_safe(item) for item in value]
    if isinstance(value, np.generic):
        return to_json_safe(value.item())
    if isinstance(value, np.ndarray):
        return to_json_safe(value.tolist())
    kind = type(value).__name__
    log.warning("Valor não serializável na telemetria: %s.", kind)
    return {"unserializable": kind}


def envelope(topic: str, ts: float, data: Any) -> str:  # noqa: ANN401
    """Monta o frame de texto `{"topic", "ts", "data"}` em JSON estrito."""
    return json.dumps(
        {"topic": topic, "ts": ts, "data": to_json_safe(data)}, allow_nan=False
    )


def _stats(values: Sequence[float]) -> dict[str, float | None]:
    if not values:
        return {"min": None, "mean": None, "max": None}
    return {
        "min": min(values),
        "mean": sum(values) / len(values),
        "max": max(values),
    }


@dataclass
class LidarMetrics:
    """Acumulador de uma janela de `lidar_metrics`.

    Os métodos `on_*` são chamados no loop (o worker repassa os tempos medidos
    na thread). :meth:`close_window` devolve o resumo e zera a janela; o
    instante da última chegada sobrevive à janela, mas não a uma pausa
    (:meth:`reset_interval`).
    """

    window_start: float
    received: int = 0
    seq_first: int | None = None
    seq_last: int | None = None
    intervals_ms: list[float] = field(default_factory=list)
    compressed_bytes: list[float] = field(default_factory=list)
    src_size: list[float] = field(default_factory=list)
    n_points: list[float] = field(default_factory=list)
    decode_ms: list[float] = field(default_factory=list)
    pipeline_ms: list[float] = field(default_factory=list)
    resolution: float | None = None
    origin: list[float] | None = None
    decoded: int = 0
    dropped_decode_queue: int = 0
    dropped_lidar_clients: int = 0
    malformed: int = 0
    decode_errors: int = 0
    last_arrival: float | None = None

    def on_received(self, seq: int, arrival: float) -> None:
        """Conta uma mensagem que chegou ao callback, válida ou não."""
        self.received += 1
        if self.seq_first is None:
            self.seq_first = seq
        self.seq_last = seq
        if self.last_arrival is not None:
            self.intervals_ms.append((arrival - self.last_arrival) * 1000)
        self.last_arrival = arrival

    def on_valid(
        self,
        compressed: int,
        src_size: int,
        resolution: float,
        origin: Sequence[float],
    ) -> None:
        """Registra os tamanhos e o grid de uma mensagem válida."""
        self.compressed_bytes.append(compressed)
        self.src_size.append(src_size)
        self.resolution = resolution
        self.origin = list(origin)

    def on_decoded(self, n_points: int, decode_ms: float, pipeline_ms: float) -> None:
        """Registra uma decodificação concluída."""
        self.decoded += 1
        self.n_points.append(n_points)
        self.decode_ms.append(decode_ms)
        self.pipeline_ms.append(pipeline_ms)

    def reset_interval(self) -> None:
        """Esquece a última chegada: o intervalo que cruza uma pausa não conta."""
        self.last_arrival = None

    def close_window(
        self,
        now: float,
        *,
        active: bool,
        last_error: str | None,
        lidar_clients: int,
        telemetry_clients: int,
    ) -> dict[str, Any]:
        """Devolve o resumo da janela.

        Quem chama começa a próxima janela com um acumulador novo, levando
        :attr:`last_arrival` para o intervalo que cruza a fronteira.
        """
        window_s = now - self.window_start
        summary: dict[str, Any] = {
            "window_s": window_s,
            "active": active,
            "last_error": last_error,
            "received": self.received,
            "rate_hz": self.received / window_s if window_s > 0 else None,
            "interval_ms": _stats(self.intervals_ms),
            "seq": {"first": self.seq_first, "last": self.seq_last},
            "compressed_bytes": _stats(self.compressed_bytes),
            "src_size": _stats(self.src_size),
            "n_points": _stats(self.n_points),
            "decode_ms": _stats(self.decode_ms),
            "pipeline_ms": _stats(self.pipeline_ms),
            "resolution": self.resolution,
            "origin": self.origin,
            "decoded": self.decoded,
            "dropped_decode_queue": self.dropped_decode_queue,
            "dropped_lidar_clients": self.dropped_lidar_clients,
            "malformed": self.malformed,
            "decode_errors": self.decode_errors,
            "clients": {"lidar": lidar_clients, "telemetry": telemetry_clients},
        }
        return summary


@dataclass(frozen=True)
class MetricsItem:
    """Resumo de uma janela, enfileirado sem serializar.

    Serializado no envio, porque o `dropped` é de cada cliente.
    """

    ts: float
    data: dict[str, Any]


class TelemetryClient:
    """Saída de um cliente de `/ws/telemetry`.

    `connection` vai numa fila própria, nunca descartada, e sai primeiro. Os
    demais tópicos dividem uma fila em ordem de chegada, com no máximo
    `queue_size` itens **por tópico**: cheia, sai o mais antigo daquele tópico
    e o cliente soma 1 em `dropped`, entregue no próximo `lidar_metrics`.
    """

    def __init__(self, queue_size: int) -> None:
        """Cria a saída com o limite por tópico."""
        self._queue_size = queue_size
        self._connection: deque[str] = deque()
        self._entries: deque[tuple[str, str | MetricsItem]] = deque()
        self._per_topic: dict[str, int] = {}
        self._dropped = 0
        self._closed: tuple[int, str] | None = None
        self._gone = False
        self._ready = asyncio.Event()

    @property
    def is_closed(self) -> bool:
        """A api decidiu fechar este cliente."""
        return self._closed is not None

    def push_connection(self, text: str) -> None:
        """Enfileira um frame `connection` (nunca descartado)."""
        self._connection.append(text)
        self._ready.set()

    def push(self, topic: str, item: str | MetricsItem) -> None:
        """Enfileira um item; texto pronto ou, para métricas, o resumo."""
        if self._per_topic.get(topic, 0) >= self._queue_size:
            for index, (queued_topic, _) in enumerate(self._entries):
                if queued_topic == topic:
                    del self._entries[index]
                    break
            self._per_topic[topic] -= 1
            self._dropped += 1
        self._entries.append((topic, item))
        self._per_topic[topic] = self._per_topic.get(topic, 0) + 1
        self._ready.set()

    def close(self, code: int, reason: str) -> None:
        """Pede o fechamento depois dos `connection` pendentes."""
        self._closed = (code, reason)
        self._ready.set()

    def mark_gone(self) -> None:
        """O cliente desconectou por conta própria."""
        self._gone = True
        self._ready.set()

    def _pop_entry(self) -> str:
        topic, item = self._entries.popleft()
        self._per_topic[topic] -= 1
        if isinstance(item, str):
            return item
        data = {**item.data, "dropped": self._dropped}
        self._dropped = 0
        return envelope(METRICS_TOPIC, item.ts, data)

    def drain(self) -> list[str]:
        """Retira tudo o que está pronto, sem esperar (testes e diagnóstico)."""
        texts = list(self._connection)
        self._connection.clear()
        while self._entries:
            texts.append(self._pop_entry())
        return texts

    async def next(self) -> ClientMessage:
        """Espera a próxima mensagem a enviar ao cliente."""
        while True:
            if self._gone:
                return ClientMessage("gone")
            if self._connection:
                return ClientMessage("text", self._connection.popleft())
            if self._closed is not None:
                code, reason = self._closed
                return ClientMessage("close", code=code, reason=reason)
            if self._entries:
                return ClientMessage("text", self._pop_entry())
            self._ready.clear()
            await self._ready.wait()
