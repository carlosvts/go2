"""Respostas de `/device/*` (F-005)."""

from pydantic import BaseModel, Field

from app.robot.device import LedColor


class DeviceLevelResponse(BaseModel):
    """Nível de brilho ou de volume.

    No `PUT` (`202`), o nível pedido, que o robô aceitou; no `GET`, o nível
    que o robô informou.
    """

    level: int = Field(description="Nível de 0 a 10.")


class LedResponse(BaseModel):
    """Pedido de LED aceito pelo robô (`202`); não prova que a cor apareceu."""

    color: LedColor
    duration_s: int
    flash_cycle_ms: int | None
