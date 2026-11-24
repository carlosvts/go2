"""Respostas de `/audio/*` (F-006)."""

from typing import Any

from pydantic import BaseModel, Field

from app.robot.audio import PlayMode, UploadState


class AudioFileResponse(BaseModel):
    """Um áudio guardado no robô."""

    id: str = Field(description="`UNIQUE_ID` do robô.")
    name: str = Field(description="`CUSTOM_NAME` do robô.")
    extra: dict[str, Any] = Field(
        description="Os outros campos do item, como vieram, sem interpretação."
    )


class AudioRenamedResponse(BaseModel):
    """Renomeação aceita pelo robô (`202`)."""

    id: str
    name: str


class AudioAccepted(BaseModel):
    """O robô aceitou o pedido (`header.status.code == 0`).

    Em `play`, não quer dizer que o som terminou nem que alguém ouviu.
    """

    accepted: bool = True


class PlayModeResponse(BaseModel):
    """Modo de reprodução: pedido e aceito (`PUT`) ou informado (`GET`)."""

    mode: PlayMode


class UploadAccepted(BaseModel):
    """Envio aceito pela api (`202`); acompanhe em `GET /audio/uploads/{id}`."""

    upload_id: str
    name: str
    total_chunks: int


class UploadStatusResponse(BaseModel):
    """Estado de um envio.

    `done` = o robô aceitou todos os blocos; a confirmação é `file_id`
    aparecer em `GET /audio/files`.
    """

    state: UploadState
    name: str
    sent_chunks: int
    total_chunks: int
    file_id: str | None = Field(
        description="Id novo na lista depois do envio; `null` se não apareceu."
    )
    error: str | None = Field(
        description="`timeout`, `disconnected`, `rejected: …` ou `error: …`."
    )


class PlayerStateResponse(BaseModel):
    """Último `AUDIO_HUB_PLAY_STATE`, cru, e há quanto tempo chegou."""

    data: Any = Field(description="`data` do tópico, sem interpretação.")
    age_s: float | None = Field(description="`null` se nada chegou ainda.")
