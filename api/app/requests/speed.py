"""Corpo de `PUT /commands/speed`."""

from pydantic import BaseModel, Field


class SpeedLevelRequest(BaseModel):
    """Nível de velocidade a aplicar no robô."""

    level: int = Field(description="Nível de velocidade, como entendido pelo robô.")
