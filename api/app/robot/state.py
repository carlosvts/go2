"""Cache do estado publicado pelo robô."""

import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

from app.robot.connection import ConnectionSnapshot, ConnectionState
from app.robot.ports import PubSub
from app.robot.sections import Section, StateSections
from app.robot.unitree import RTC_TOPIC

log = logging.getLogger(__name__)


class StateSource(StrEnum):
    """Tópico de origem das seções de estado (nome usado no `state_metrics`)."""

    low_state = "low_state"
    sport_state = "sport_state"
    multiple_state = "multiple_state"


SECTION_ORDER: tuple[str, ...] = (
    "battery",
    "imu",
    "motion",
    "motors",
    "body_temperature_c",
    "settings",
)
"""Ordem das seções no `/status` e no aceite do `/ws/state`."""

SECTION_SOURCES: dict[str, StateSource] = {
    "battery": StateSource.low_state,
    "imu": StateSource.sport_state,
    "motion": StateSource.sport_state,
    "motors": StateSource.low_state,
    "body_temperature_c": StateSource.low_state,
    "settings": StateSource.multiple_state,
}
"""Tópico de origem que alimenta cada seção."""

StateListener = Callable[[StateSource, float], None]
"""Recebe a origem e o instante (Unix) da chegada de cada mensagem de estado."""


@dataclass(frozen=True)
class RobotStatus:
    """Snapshot lido do cache em memória — não gera tráfego novo com o robô."""

    connected: bool
    state: ConnectionState
    since: datetime
    battery_percent: int | None
    mode: int | None
    sport_state_age_s: float | None
    low_state_age_s: float | None
    multiple_state_age_s: float | None = None
    battery: Section | None = None
    imu: Section | None = None
    motion: Section | None = None
    motors: list[Section | None] | None = None
    body_temperature_c: int | float | None = None
    settings: Section | None = None
    errors: list[dict[str, Any]] | None = None


@dataclass
class _TimedPayload:
    """Último payload recebido de um tópico e o instante da chegada."""

    data: dict[str, Any] | None = None
    received_at: float | None = None
    received_wall: float | None = None

    def store(self, data: dict[str, Any] | None, now: float, wall: float) -> None:
        """Substitui o payload guardado."""
        self.data = data
        self.received_at = now
        self.received_wall = wall

    def age(self, now: float) -> float | None:
        """Segundos desde a chegada; `None` se nada chegou ainda."""
        if self.received_at is None:
            return None
        return now - self.received_at


class StateCache:
    """Observer dos tópicos de estado: guarda o último payload de cada um.

    `GET /status` lê deste cache, sem round-trip novo a cada chamada, e o
    `/ws/state` também (a lib guarda um callback por tópico: assinar de novo
    tiraria o do `/status`). Os callbacks são síncronos e só guardam o dado —
    padrão exigido pelo webrtc_bridge, que entrega a mensagem inteira
    `{"type", "topic", "data"}`. Depois de guardar, avisam os ouvintes.
    """

    def __init__(
        self,
        clock: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], float] = time.time,
    ) -> None:
        """Recebe os relógios (injetáveis para testes determinísticos).

        Args:
            clock: Relógio monotônico, para as idades.
            wall_clock: Relógio de parede (Unix), para o `ts` do `/ws/state`.
        """
        self._clock = clock
        self._wall_clock = wall_clock
        self._payloads = {source: _TimedPayload() for source in StateSource}
        self._listeners: list[StateListener] = []

    def attach(self, pub_sub: PubSub) -> None:
        """Assina os tópicos de estado — uma única vez, na conexão."""
        pub_sub.subscribe(RTC_TOPIC["SPORT_MOD_STATE"], self.on_sport_state)
        pub_sub.subscribe(RTC_TOPIC["LOW_STATE"], self.on_low_state)
        pub_sub.subscribe(RTC_TOPIC["MULTIPLE_STATE"], self.on_multiple_state)

    def subscribe(self, listener: StateListener) -> None:
        """Registra `listener` para cada mensagem de estado guardada."""
        self._listeners.append(listener)

    def on_sport_state(self, message: dict[str, Any]) -> None:
        """Guarda o último `rt/sportmodestate`."""
        self._store(StateSource.sport_state, message.get("data"))

    def on_low_state(self, message: dict[str, Any]) -> None:
        """Guarda o último `rt/lf/lowstate`."""
        self._store(StateSource.low_state, message.get("data"))

    def on_multiple_state(self, message: dict[str, Any]) -> None:
        """Guarda o último `rt/multiplestate`, decodificando o `data` em string.

        `data` que não é JSON de um objeto deixa `settings` `None` (log).
        """
        data = message.get("data")
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except ValueError:
                log.warning("MULTIPLE_STATE com data que não é JSON: %.200r", data)
                data = None
        if data is not None and not isinstance(data, dict):
            log.warning("MULTIPLE_STATE com data que não é objeto: %.200r", data)
            data = None
        self._store(StateSource.multiple_state, data)

    def _store(self, source: StateSource, data: object) -> None:
        wall = self._wall_clock()
        self._payloads[source].store(
            data if isinstance(data, dict) else None, self._clock(), wall
        )
        for listener in self._listeners:
            try:
                listener(source, wall)
            except Exception:
                log.exception("❌ Falha num ouvinte do estado.")

    # ─── Seções ────────────────────────────────────────────────────────────

    def section(self, topic: str) -> Any:  # noqa: ANN401 - seção já pronta para JSON
        """Valor atual da seção `topic` (`None` se a origem nunca chegou)."""
        data = self._payloads[SECTION_SOURCES[topic]].data
        extract: Callable[[object], Any] = getattr(StateSections, topic)
        return extract(data)

    def sections_of(self, source: StateSource) -> dict[str, Any]:
        """Seções alimentadas por `source`, na ordem de :data:`SECTION_ORDER`."""
        return {
            topic: self.section(topic)
            for topic in SECTION_ORDER
            if SECTION_SOURCES[topic] is source
        }

    def current_sections(self) -> list[tuple[str, float, Any]]:
        """`(tópico, chegada Unix, valor)` de cada seção não nula, em ordem."""
        frames: list[tuple[str, float, Any]] = []
        for topic in SECTION_ORDER:
            payload = self._payloads[SECTION_SOURCES[topic]]
            value = self.section(topic)
            if value is not None and payload.received_wall is not None:
                frames.append((topic, payload.received_wall, value))
        return frames

    def snapshot(
        self,
        *,
        connected: bool,
        connection: ConnectionSnapshot,
        errors: list[dict[str, Any]] | None = None,
    ) -> RobotStatus:
        """Extrai bateria, modo, seções e idades do cache. Campo ilegível vira `None`.

        Args:
            connected: Se a conexão aceita comandos (`is_connected`).
            connection: Estado publicado da conexão e desde quando vale.
            errors: Erros ativos do data channel (`None` = desconhecido).
        """
        now = self._clock()
        low = self._payloads[StateSource.low_state]
        sport = self._payloads[StateSource.sport_state]
        multiple = self._payloads[StateSource.multiple_state]
        return RobotStatus(
            connected=connected,
            state=connection.state,
            since=connection.since,
            battery_percent=StateSections.battery_percent(low.data),
            mode=StateSections.mode(sport.data),
            sport_state_age_s=sport.age(now),
            low_state_age_s=low.age(now),
            multiple_state_age_s=multiple.age(now),
            battery=StateSections.battery(low.data),
            imu=StateSections.imu(sport.data),
            motion=StateSections.motion(sport.data),
            motors=StateSections.motors(low.data),
            body_temperature_c=StateSections.body_temperature_c(low.data),
            settings=StateSections.settings(multiple.data),
            errors=errors,
        )

    @property
    def raw(self) -> dict[str, dict[str, Any] | None]:
        """Payloads crus em cache, sem interpretação (`multiple_state` decodificado)."""
        return {
            "sport_mode_state": self._payloads[StateSource.sport_state].data,
            "low_state": self._payloads[StateSource.low_state].data,
            "multiple_state": self._payloads[StateSource.multiple_state].data,
        }
