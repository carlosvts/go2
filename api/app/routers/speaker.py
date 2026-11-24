"""Alto-falante: `POST /speaker/play`, `POST /speaker/stop`, `GET /speaker`.

Toca um WAV ou MP3 pela track de áudio WebRTC, sem guardar nada no robô
(F-007). `202` = a api aceitou e passou a enviar; não prova que o robô
reproduziu. Estas rotas não entram no `/capabilities`.
"""

from typing import Any

from fastapi import APIRouter, Request, status

from app.dependencies import RobotDep, SettingsDep
from app.exceptions import RobotUnavailableError
from app.requests.upload import read_multipart
from app.responses.speaker import (
    PlaybackResponse,
    SpeakerResponse,
    SpeakerStopResponse,
)
from app.robot.link import NOT_CONNECTED_MESSAGE

router = APIRouter(prefix="/speaker", tags=["speaker"])

_PLAY_ERRORS: dict[int | str, dict[str, Any]] = {
    413: {"description": "Arquivo acima de `GO2_AUDIO_MAX_UPLOAD_MB`."},
    415: {"description": "Não é WAV nem MP3 (pelo conteúdo) ou não decodifica."},
    422: {"description": "Sem `multipart/form-data` ou sem o campo `file`."},
    503: {"description": "Sem conexão com o robô."},
}

_MULTIPART_BODY: dict[str, Any] = {
    "requestBody": {
        "required": True,
        "content": {
            "multipart/form-data": {
                "schema": {
                    "type": "object",
                    "required": ["file"],
                    "properties": {
                        "file": {
                            "type": "string",
                            "format": "binary",
                            "description": "WAV ou MP3.",
                        }
                    },
                }
            }
        },
    }
}


@router.post(
    "/play",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=PlaybackResponse,
    responses=_PLAY_ERRORS,
    openapi_extra=_MULTIPART_BODY,
    summary="Toca um WAV ou MP3 no alto-falante, substituindo o atual",
)
async def play(
    request: Request, robot: RobotDep, settings: SettingsDep
) -> PlaybackResponse:
    """Lê o upload (até o teto), decodifica numa thread e começa a enviar.

    Um `play` ou `stop` que chegue durante a decodificação vence: este
    responde `202` mas não toca.
    """
    if not robot.is_connected:
        raise RobotUnavailableError(NOT_CONNECTED_MESSAGE)
    upload = await read_multipart(
        request.headers.get("content-type"),
        request.headers.get("content-length"),
        request.stream(),
        max_bytes=settings.audio_max_upload_bytes,
    )
    playback = await robot.speaker.play(upload.data, upload.filename or "audio")
    return PlaybackResponse(
        playback_id=playback.playback_id,
        name=playback.name,
        duration_s=playback.duration_s,
    )


@router.post(
    "/stop",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=SpeakerStopResponse,
    summary="Cala o alto-falante",
)
async def stop(robot: RobotDep) -> SpeakerStopResponse:
    """Volta ao silêncio e cancela `play` em decodificação; vale sem conexão."""
    await robot.speaker.stop()
    return SpeakerStopResponse()


@router.get("", response_model=SpeakerResponse, summary="O que está tocando")
async def get_speaker(robot: RobotDep) -> SpeakerResponse:
    """`playing` quer dizer que a api está enviando o áudio."""
    snapshot = robot.speaker.snapshot
    return SpeakerResponse(
        state=snapshot.state,
        playback_id=snapshot.playback_id,
        name=snapshot.name,
        started_at=snapshot.started_at,
        duration_s=snapshot.duration_s,
    )
