"""Resposta de `GET /status`."""

from datetime import datetime
from typing import Any, Self

from pydantic import BaseModel, Field

from app.robot.connection import ConnectionState
from app.robot.state import RobotStatus


class StatusResponse(BaseModel):
    """Snapshot do estado do robô, lido do cache."""

    connected: bool = Field(
        description="Há conexão WebRTC viva e canal de dados validado. É o que "
        "decide se os comandos são aceitos ou levam `503`."
    )
    state: ConnectionState = Field(
        description="Estado publicado da conexão. `reconnecting`: a conexão "
        "caiu e a API está tentando de novo, sozinha."
    )
    since: datetime = Field(description="Momento (UTC) da última transição de `state`.")
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
            state=status.state,
            since=status.since,
            battery_percent=status.battery_percent,
            mode=status.mode,
            sport_state_age_s=status.sport_state_age_s,
            low_state_age_s=status.low_state_age_s,
            raw=raw,
        )
