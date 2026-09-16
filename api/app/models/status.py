"""Schema de `GET /status`."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class StatusResponse(BaseModel):
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
