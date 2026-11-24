"""Respostas de `/speaker/*` (F-007)."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class PlaybackResponse(BaseModel):
    """`play` aceito (`202`): a api começou a enviar, não prova que o robô tocou."""

    playback_id: str
    name: str = Field(description="Nome do arquivo enviado.")
    duration_s: float = Field(description="Amostras decodificadas ÷ taxa.")


class SpeakerStopResponse(BaseModel):
    """`stop` aceito (`202`), também quando nada tocava."""

    state: Literal["idle"] = "idle"


class SpeakerResponse(BaseModel):
    """O que o alto-falante está fazendo. `playing` = a api está enviando."""

    state: Literal["idle", "playing"]
    playback_id: str | None
    name: str | None
    started_at: datetime | None = Field(description="Início do envio (UTC).")
    duration_s: float | None
