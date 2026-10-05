"""Vocabulário de comandos esportivos e objetos de valor de movimento.

Os objetos daqui validam a si mesmos na construção: um :class:`MoveCommand`
fora dos limites levanta :class:`~app.exceptions.InvalidCommandError` e,
portanto, nunca chega ao robô nem precisa ser re-checado por quem o recebe.
"""

import math
from dataclasses import InitVar, dataclass
from enum import StrEnum

from app.exceptions import InvalidCommandError


class SportCommand(StrEnum):
    """Base dos enums de comandos esportivos (posturas, gestos, ...).

    O valor é `snake_case` (como aparece no JSON da request) e `sport_cmd`
    dá a chave `CamelCase` correspondente em `SPORT_CMD`. Subclasses só
    declaram membros — `auto()` já gera o valor igual ao nome:

        class Gesture(SportCommand):
            hello = auto()
            finger_heart = auto()
    """

    @property
    def sport_cmd(self) -> str:
        """Chave em `SPORT_CMD` (ex.: `stand_up` -> `StandUp`)."""
        return "".join(part.capitalize() for part in self.value.split("_"))


@dataclass(frozen=True)
class MoveLimits:
    """Tetos aceitos para um movimento, vindos da configuração."""

    max_vx: float
    max_vy: float
    max_vyaw: float
    max_duration_s: float


@dataclass(frozen=True)
class MoveCommand:
    """Movimento contínuo no referencial do robô, já validado.

    A construção falha com :class:`InvalidCommandError` se algum valor for
    não finito, se a duração não for positiva ou se algum teto de `limits`
    for excedido. `limits` é só um parâmetro de construção: não é guardado.
    """

    vx: float
    vy: float
    vyaw: float
    duration_s: float
    limits: InitVar[MoveLimits]

    def __post_init__(self, limits: MoveLimits) -> None:
        """Valida os valores contra os limites, levantando se houver problema."""
        problems = self._non_finite_fields()
        if not problems:
            problems = self._limit_violations(limits)
        if problems:
            raise InvalidCommandError("; ".join(problems))

    @property
    def parameter(self) -> dict[str, float]:
        """Parâmetro do `Move` (1008), no formato exigido pelo webrtc_bridge.

        Usa `x`/`y`/`z`, com `z` sendo o yaw — como no exemplo `sportmode.py`
        da lib. Com `yaw` o robô ignora o comando. Fonte única do payload:
        o disparo inicial e o reenvio periódico usam o mesmo objeto.
        """
        return {"x": self.vx, "y": self.vy, "z": self.vyaw}

    def _non_finite_fields(self) -> list[str]:
        """Lista os campos NaN/infinitos, que passariam despercebidos pelos tetos."""
        values = {
            "vx": self.vx,
            "vy": self.vy,
            "vyaw": self.vyaw,
            "duration_s": self.duration_s,
        }
        problems: list[str] = []
        for name, value in values.items():
            if not math.isfinite(value):
                problems.append(f"{name} deve ser um número finito")
        return problems

    def _limit_violations(self, limits: MoveLimits) -> list[str]:
        """Lista as violações de duração e de velocidade."""
        problems: list[str] = []
        if self.duration_s <= 0:
            problems.append("duration_s deve ser positivo")
        elif self.duration_s > limits.max_duration_s:
            problems.append(
                f"duration_s excede GO2_MOVE_MAX_DURATION_S "
                f"({limits.max_duration_s}s)"
            )
        speeds = {
            "vx": (self.vx, limits.max_vx),
            "vy": (self.vy, limits.max_vy),
            "vyaw": (self.vyaw, limits.max_vyaw),
        }
        exceeded: list[str] = []
        for name, (value, ceiling) in speeds.items():
            if abs(value) > ceiling:
                exceeded.append(name)
        if exceeded:
            problems.append(f"Fora do limite configurado: {', '.join(exceeded)}")
        return problems
