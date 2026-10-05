"""Resposta de `GET /status`."""

from typing import Any, Self

from pydantic import BaseModel, Field

from app.robot.state import RobotStatus


class StatusResponse(BaseModel):
    """Snapshot do estado do robô, lido do cache."""

    connected: bool = Field(
        description="Há conexão WebRTC viva e canal de dados validado."
    )
    battery_percent: int | None = Field(
        default=None,
        description="Carga em %, do cache de `rt/lf/lowstate`. `null` se ainda "
        "não chegou estado ou se o campo não foi reconhecido.",
    )
    mode: int | None = Field(
        default=None, description="Modo atual, do cache de `rt/sportmodestate`."
    )
    sport_state_age_s: float | None = Field(
        default=None,
        description="Há quantos segundos chegou o último `rt/sportmodestate`.",
    )
    low_state_age_s: float | None = Field(
        default=None,
        description="Há quantos segundos chegou o último `rt/lf/lowstate`.",
    )
    raw: dict[str, Any] | None = Field(
        default=None,
        description="Payloads crus em cache. Presente para permitir fixar a "
        "extração de `battery_percent`/`mode` na validação com o robô ligado.",
    )

    @classmethod
    def from_status(cls, status: RobotStatus, raw: dict[str, Any] | None) -> Self:
        """Converte o snapshot de domínio na resposta HTTP.

        Args:
            status: Snapshot lido do cache.
            raw: Payloads crus, ou `None` para omiti-los.
        """
        return cls(
            connected=status.connected,
            battery_percent=status.battery_percent,
            mode=status.mode,
            sport_state_age_s=status.sport_state_age_s,
            low_state_age_s=status.low_state_age_s,
            raw=raw,
        )
