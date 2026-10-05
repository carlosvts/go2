"""Resposta de `GET /commands/speed`."""

from typing import Any, Self

from pydantic import BaseModel, Field

from app.robot.speed import SpeedReading


class SpeedLevelResponse(BaseModel):
    """Nível de velocidade informado pelo robô."""

    level: int | None = Field(
        description=(
            "Nível informado pelo robô. Vem `null` quando a resposta não pôde "
            "ser interpretada — consulte `raw` nesse caso."
        )
    )
    raw: Any = Field(
        default=None,
        description="Resposta crua do robô, sem interpretação.",
    )

    @classmethod
    def from_reading(cls, reading: SpeedReading) -> Self:
        """Converte a leitura de domínio na resposta HTTP."""
        return cls(level=reading.level, raw=reading.raw)
