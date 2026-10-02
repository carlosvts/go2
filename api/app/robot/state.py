"""Cache do estado publicado pelo robô."""

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, ClassVar

from app.robot.payload import PayloadReader
from app.robot.ports import PubSub
from app.robot.unitree import RTC_TOPIC


@dataclass(frozen=True)
class RobotStatus:
    """Snapshot lido do cache em memória — não gera tráfego novo com o robô."""

    connected: bool
    battery_percent: int | None
    mode: int | None
    sport_state_age_s: float | None
    low_state_age_s: float | None


@dataclass
class _TimedPayload:
    """Último payload recebido de um tópico e o instante da chegada."""

    data: dict[str, Any] | None = None
    received_at: float | None = None

    def store(self, data: dict[str, Any] | None, now: float) -> None:
        """Substitui o payload guardado."""
        self.data = data
        self.received_at = now

    def age(self, now: float) -> float | None:
        """Segundos desde a chegada; `None` se nada chegou ainda."""
        if self.received_at is None:
            return None
        return now - self.received_at


class StateCache:
    """Observer dos tópicos de estado: guarda o último payload de cada um.

    `GET /status` lê deste cache, sem round-trip novo a cada chamada. Os
    callbacks são síncronos e só guardam o dado — padrão exigido pelo
    webrtc_bridge, que entrega a mensagem inteira `{"type", "topic", "data"}`.
    """

    # Pendente de validação física: caminhos até bateria e modo. Fixar com
    # `GET /status?raw=true` no robô ligado.
    _BATTERY_PATHS: ClassVar[tuple[tuple[str, ...], ...]] = (
        ("bms_state", "soc"),
        ("bms", "soc"),
        ("soc",),
    )
    _MODE_PATHS: ClassVar[tuple[tuple[str, ...], ...]] = (("mode",),)

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        """Recebe o relógio (injetável para testes determinísticos)."""
        self._clock = clock
        self._sport = _TimedPayload()
        self._low = _TimedPayload()

    def attach(self, pub_sub: PubSub) -> None:
        """Assina os tópicos de estado — uma única vez, na conexão."""
        pub_sub.subscribe(RTC_TOPIC["SPORT_MOD_STATE"], self.on_sport_state)
        pub_sub.subscribe(RTC_TOPIC["LOW_STATE"], self.on_low_state)

    def on_sport_state(self, message: dict[str, Any]) -> None:
        """Guarda o último `rt/sportmodestate`."""
        self._sport.store(message.get("data"), self._clock())

    def on_low_state(self, message: dict[str, Any]) -> None:
        """Guarda o último `rt/lf/lowstate`."""
        self._low.store(message.get("data"), self._clock())

    def snapshot(self, *, connected: bool) -> RobotStatus:
        """Extrai bateria, modo e idades do cache. Campo ilegível vira `None`."""
        now = self._clock()
        battery = PayloadReader.first_path(self._low.data, *self._BATTERY_PATHS)
        mode = PayloadReader.first_path(self._sport.data, *self._MODE_PATHS)
        return RobotStatus(
            connected=connected,
            battery_percent=battery if isinstance(battery, int) else None,
            mode=mode if isinstance(mode, int) else None,
            sport_state_age_s=self._sport.age(now),
            low_state_age_s=self._low.age(now),
        )

    @property
    def raw(self) -> dict[str, dict[str, Any] | None]:
        """Payloads crus em cache, sem interpretação."""
        return {"sport_mode_state": self._sport.data, "low_state": self._low.data}
