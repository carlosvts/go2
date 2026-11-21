"""Stream do estado do robô para `/ws/state` (F-004).

Fluxo:

```
StateCache (tópicos LOW/SPORT/MULTIPLE_STATE, os mesmos do /status)
   ─▶ seções da mensagem ─▶ JSON montado uma vez
   ─▶ cada cliente: teto por tópico + 1 pendente por tópico (o mais recente)
ActiveErrors e transições da conexão
   ─▶ caminho próprio de cada cliente: sem descarte e sem teto, em ordem
```

O stream não assina nem cancela nada no robô: só lê o cache.

Pontos de extensão (para F-006/F-007 e outros tópicos):

- :meth:`StateStream.publish_event`: tópico "sem descarte", como `errors`
  (eventos, mudanças de estado que o cliente não pode perder);
- :meth:`StateStream.publish_section`: tópico de seção, com o teto
  `GO2_STATE_MAX_HZ` e um pendente por cliente (o mais recente);
- :meth:`StateStream.add_snapshot_provider`: valores atuais enviados no
  aceite, depois das seções e antes de `errors`.
"""

import asyncio
import contextlib
import json
import logging
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from app.robot.clients import ClientMessage
from app.robot.connection import ConnectionState
from app.robot.errors import ActiveError, ActiveErrors
from app.robot.link import RobotLink
from app.robot.state import StateCache, StateSource
from app.robot.streams import state_text
from app.robot.telemetry import envelope

__all__ = ["StateClient", "StateStream"]

log = logging.getLogger(__name__)

CLOSE_SHUTDOWN = (1001, "shutdown")
ERRORS_TOPIC = "errors"
ERRORS_METRIC = "errors"
"""Nome da origem "mensagens de erro do data channel" no `state_metrics`."""

SnapshotProvider = Callable[[], list[tuple[str, float, Any]]]
"""Devolve `(tópico, ts, data)` dos valores atuais a enviar no aceite."""


@dataclass
class _Slot:
    """Frame de seção à espera de envio; o mais recente substitui o texto."""

    topic: str
    text: str


class StateClient:
    """Saída de um cliente de `/ws/state`.

    Uma fila só, em ordem de chegada, com dois tipos de item:

    - eventos (`connection`, `errors`, :meth:`StateStream.publish_event`):
      nunca descartados nem limitados;
    - seções: no máximo **um pendente por tópico**. Um frame novo do tópico
      substitui o pendente (soma 1 em :attr:`dropped`). Por tópico, entra na
      fila no máximo um frame a cada `min_interval_s`; acima disso o mais
      recente fica retido e entra quando a janela fecha, mesmo que o tópico
      pare de chegar.
    """

    def __init__(
        self,
        min_interval_s: float,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        """Cria a saída com o intervalo mínimo por tópico (`0` = sem teto)."""
        self._min_interval_s = min_interval_s
        self._monotonic = monotonic
        self._queue: deque[str | _Slot] = deque()
        self._queued: dict[str, _Slot] = {}
        self._held: dict[str, str] = {}
        self._next_allowed: dict[str, float] = {}
        self._close: tuple[int, str] | None = None
        self._gone = False
        self._ready = asyncio.Event()
        self.sent = 0
        """Frames entregues ao WebSocket (ou a :meth:`drain`) desde a criação."""
        self.dropped = 0
        """Frames de seção substituídos antes de sair, desde a criação."""

    @property
    def is_closed(self) -> bool:
        """A api decidiu fechar este cliente."""
        return self._close is not None

    def push_event(self, text: str) -> None:
        """Enfileira um evento: sem descarte e sem teto."""
        if self._close is not None:
            return
        self._queue.append(text)
        self._ready.set()

    def push_section(self, topic: str, text: str, now: float) -> None:
        """Oferece um frame de seção, respeitando o teto e o pendente único."""
        if self._close is not None:
            return
        slot = self._queued.get(topic)
        if slot is not None:
            slot.text = text
            self.dropped += 1
            return
        if topic in self._held:
            self._held[topic] = text
            self.dropped += 1
            return
        if now >= self._next_allowed.get(topic, now):
            self._enqueue(topic, text, now)
        else:
            self._held[topic] = text
            self._ready.set()  # o `next` passa a esperar o fim da janela

    def _enqueue(self, topic: str, text: str, now: float) -> None:
        slot = _Slot(topic, text)
        self._queue.append(slot)
        self._queued[topic] = slot
        self._next_allowed[topic] = now + self._min_interval_s
        self._ready.set()

    def _release_due(self, now: float) -> float | None:
        """Põe na fila os retidos cuja janela fechou; devolve o próximo prazo."""
        upcoming: float | None = None
        for topic in list(self._held):
            due = self._next_allowed[topic]
            if now >= due:
                self._enqueue(topic, self._held.pop(topic), now)
            elif upcoming is None or due < upcoming:
                upcoming = due
        return upcoming

    def _pop(self) -> str:
        item = self._queue.popleft()
        self.sent += 1
        if isinstance(item, str):
            return item
        del self._queued[item.topic]
        return item.text

    def pending_section_count(self) -> int:
        """Frames de seção pendentes (na fila ou retidos pelo teto)."""
        return len(self._queued) + len(self._held)

    def close(self, code: int, reason: str) -> None:
        """Pede o fechamento depois dos eventos pendentes; descarta as seções."""
        self._close = (code, reason)
        self._queue = deque(item for item in self._queue if isinstance(item, str))
        self._queued.clear()
        self._held.clear()
        self._ready.set()

    def mark_gone(self) -> None:
        """O cliente desconectou por conta própria."""
        self._gone = True
        self._ready.set()

    def drain(self) -> list[str]:
        """Retira tudo o que está pronto agora, sem esperar (testes e diagnóstico)."""
        self._release_due(self._monotonic())
        texts: list[str] = []
        while self._queue:
            texts.append(self._pop())
        return texts

    async def next(self) -> ClientMessage:
        """Espera a próxima mensagem a enviar ao cliente."""
        while True:
            if self._gone:
                return ClientMessage("gone")
            upcoming = self._release_due(self._monotonic())
            if self._queue:
                return ClientMessage("text", self._pop())
            if self._close is not None:
                code, reason = self._close
                return ClientMessage("close", code=code, reason=reason)
            self._ready.clear()
            if upcoming is None:
                await self._ready.wait()
            else:
                timeout = max(0.0, upcoming - self._monotonic())
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(self._ready.wait(), timeout)


class StateStream:
    """Liga o cache de estado e os erros ativos aos clientes de `/ws/state`."""

    def __init__(  # noqa: PLR0913 - configuração explícita, sem objeto extra
        self,
        link: RobotLink,
        cache: StateCache,
        errors: ActiveErrors,
        *,
        max_clients: int,
        max_hz: float,
        metrics_interval_s: float | None = 1.0,
        clock: Callable[[], float] = time.time,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        """Recebe as fontes e os limites; ouve a conexão, o cache e os erros.

        Args:
            link: Conexão com o robô (só o estado publicado dela).
            cache: Cache de estado do `/status`.
            errors: Erros ativos do data channel.
            max_clients: Limite de `/ws/state` (`0` desliga a rota).
            max_hz: Teto por cliente e por tópico de seção; `0` = sem teto.
            metrics_interval_s: Janela do `state_metrics` no log; `None`
                desliga o relógio (os testes chamam :meth:`emit_metrics`).
            clock: Relógio de parede (`ts` do `connection`).
            monotonic: Relógio monotônico (teto e janela das métricas).
        """
        self._link = link
        self._cache = cache
        self._errors = errors
        self._max_clients = max_clients
        self._min_interval_s = 1.0 / max_hz if max_hz > 0 else 0.0
        self._metrics_interval_s = metrics_interval_s
        self._clock = clock
        self._monotonic = monotonic
        self._clients: list[StateClient] = []
        self._providers: list[SnapshotProvider] = []
        self._received = dict.fromkeys([*StateSource, ERRORS_METRIC], 0)
        self._errors_seen = errors.message_count
        self._window_start = monotonic()
        self._last_counts: dict[int, tuple[int, int]] = {}
        self._ticker: asyncio.Task[None] | None = None
        link.state.subscribe(self.on_connection)
        cache.subscribe(self.on_state)
        errors.subscribe(self.on_errors)

    # ─── Ciclo de vida ─────────────────────────────────────────────────────

    def start(self) -> None:
        """Sobe o relógio do `state_metrics`."""
        if self._ticker is None and self._metrics_interval_s is not None:
            self._ticker = asyncio.create_task(self._tick(self._metrics_interval_s))

    async def stop(self) -> None:
        """Fecha os clientes com `1001` e para o relógio."""
        for client in self._clients:
            client.close(*CLOSE_SHUTDOWN)
        self._clients.clear()
        if self._ticker is not None:
            self._ticker.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._ticker
            self._ticker = None

    # ─── Clientes ──────────────────────────────────────────────────────────

    def add_client(self) -> StateClient | None:
        """Registra um cliente; `None` se o limite foi atingido.

        Enfileira, em ordem: `connection`, o valor atual de cada seção não
        nula (com o `ts` da chegada original), os provedores extras e `errors`.
        """
        if len(self._clients) >= self._max_clients:
            return None
        client = StateClient(self._min_interval_s, self._monotonic)
        now = self._monotonic()
        client.push_event(self._connection_text(self._link.state.current.state))
        initial = list(self._cache.current_sections())
        for provider in self._providers:
            try:
                initial += provider()
            except Exception:
                log.exception("❌ Falha num provedor do aceite do /ws/state.")
        for topic, ts, data in initial:
            client.push_section(topic, envelope(topic, ts, data), now)
        client.push_event(envelope(ERRORS_TOPIC, self._clock(), self._errors.current))
        self._clients.append(client)
        return client

    def remove_client(self, client: StateClient) -> None:
        """Tira o cliente do stream."""
        if client in self._clients:
            self._clients.remove(client)
        self._last_counts.pop(id(client), None)

    def client_count(self) -> int:
        """Clientes conectados."""
        return len(self._clients)

    # ─── Pontos de extensão ────────────────────────────────────────────────

    def publish_event(self, topic: str, data: Any, *, ts: float | None = None) -> None:  # noqa: ANN401
        """Envia `{"topic", "ts", "data"}` a todos, sem descarte e sem teto.

        Para eventos que o cliente não pode perder (como `errors`). O JSON é
        montado uma vez. Sem `ts`, usa o relógio de parede agora.
        """
        if not self._clients:
            return
        text = envelope(topic, self._clock() if ts is None else ts, data)
        for client in self._clients:
            client.push_event(text)

    def publish_section(
        self,
        topic: str,
        data: Any,  # noqa: ANN401
        *,
        ts: float | None = None,
    ) -> None:
        """Envia um frame de seção a todos, com teto e um pendente por cliente.

        Para valores em que só o mais recente importa. Sem `ts`, usa o relógio
        de parede agora.
        """
        if not self._clients:
            return
        text = envelope(topic, self._clock() if ts is None else ts, data)
        now = self._monotonic()
        for client in self._clients:
            client.push_section(topic, text, now)

    def add_snapshot_provider(self, provider: SnapshotProvider) -> None:
        """Acrescenta valores atuais ao aceite (depois das seções, antes de `errors`).

        Os frames do provedor seguem o caminho das seções.
        """
        self._providers.append(provider)

    # ─── Fontes ────────────────────────────────────────────────────────────

    def on_state(self, source: StateSource, ts: float) -> None:
        """Mensagem de estado guardada: um frame por seção que ela alimenta."""
        self._received[source] += 1
        if not self._clients:
            return
        for topic, data in self._cache.sections_of(source).items():
            self.publish_section(topic, data, ts=ts)

    def on_errors(self, errors: list[ActiveError] | None, ts: float) -> None:
        """A lista de erros mudou."""
        self.publish_event(ERRORS_TOPIC, errors, ts=ts)

    def on_connection(self, payload: dict[str, str]) -> None:
        """Repassa a transição; fora de `connected`, também `errors: null`."""
        state = ConnectionState(payload["state"])
        text = self._connection_text(state)
        for client in self._clients:
            client.push_event(text)
        if state is not ConnectionState.connected:
            self.publish_event(ERRORS_TOPIC, None)

    def _connection_text(self, state: ConnectionState) -> str:
        return state_text("connection", self._clock(), state.value)

    # ─── Métricas ──────────────────────────────────────────────────────────

    def emit_metrics(self) -> dict[str, Any]:
        """Fecha a janela, registra `state_metrics` (INFO) e devolve o resumo."""
        now = self._monotonic()
        window_s = now - self._window_start
        self._received[ERRORS_METRIC] = self._errors.message_count - self._errors_seen
        clients: list[dict[str, int]] = []
        for client in self._clients:
            sent, dropped = self._last_counts.get(id(client), (0, 0))
            clients.append(
                {"sent": client.sent - sent, "dropped": client.dropped - dropped}
            )
            self._last_counts[id(client)] = (client.sent, client.dropped)
        summary: dict[str, Any] = {
            "window_s": window_s,
            "received": {str(key): value for key, value in self._received.items()},
            "rate_hz": {
                str(key): value / window_s if window_s > 0 else None
                for key, value in self._received.items()
            },
            "clients": clients,
        }
        self._reset_window(now)
        log.info("state_metrics %s", json.dumps(summary))
        return summary

    async def _tick(self, interval_s: float) -> None:
        while True:
            await asyncio.sleep(interval_s)
            if self._clients:
                self.emit_metrics()
            else:
                self._reset_window(self._monotonic())

    def _reset_window(self, now: float) -> None:
        self._received = dict.fromkeys(self._received, 0)
        self._errors_seen = self._errors.message_count
        self._window_start = now
