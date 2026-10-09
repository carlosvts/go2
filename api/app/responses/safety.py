"""Resposta de `GET /safety/obstacle-avoidance`."""

from typing import Any, Self

from pydantic import BaseModel, Field

from app.robot.safety import ObstacleAvoidanceReading


class ObstacleAvoidanceResponse(BaseModel):
    """Estado do desvio de obstáculo informado pelo robô."""

    enabled: bool | None = Field(
        description=(
            "Se o desvio está ligado. Vem `null` quando a resposta não pôde "
            "ser interpretada — consulte `raw` nesse caso."
        )
    )
    raw: Any = Field(
        default=None,
        description="Resposta crua do robô, sem interpretação.",
    )

    @classmethod
    def from_reading(cls, reading: ObstacleAvoidanceReading) -> Self:
        """Converte a leitura de domínio na resposta HTTP."""
        return cls(enabled=reading.enabled, raw=reading.raw)
