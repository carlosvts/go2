"""Corpo de `PUT /safety/obstacle-avoidance`."""

from pydantic import BaseModel, Field


class ObstacleAvoidanceRequest(BaseModel):
    """Liga ou desliga o desvio de obstáculo nativo do robô."""

    enabled: bool = Field(
        strict=True, description="`true` liga o desvio de obstáculo; `false` desliga."
    )
