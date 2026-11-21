"""Biblioteca de áudio do robô: `/audio/*` (F-006).

Como em `/device/*` (F-005), toda escrita espera a resposta do robô: `202`
= o robô **aceitou** (`header.status.code == 0`). Em `play`, isso não quer
dizer que o som terminou nem que alguém ouviu. Em `502` e `504`, o estado do
robô é desconhecido. A api não confere se o `id` existe: quem responde é o
robô. Estas rotas não entram no `/capabilities`.
"""

from typing import Any

from fastapi import APIRouter, Request, status

from app.dependencies import RobotDep
from app.requests.audio import AudioRenameRequest, PlayModeRequest
from app.requests.library_upload import StreamingUpload
from app.responses.audio import (
    AudioAccepted,
    AudioFileResponse,
    AudioRenamedResponse,
    PlayerStateResponse,
    PlayModeResponse,
    UploadAccepted,
    UploadStatusResponse,
)
from app.robot.audio import UploadSource

router = APIRouter(prefix="/audio", tags=["audio"])

_ERRORS: dict[int | str, dict[str, Any]] = {
    502: {"description": "O robô recusou (código ≠ 0) ou respondeu algo ilegível."},
    503: {"description": "Sem conexão com o robô."},
    504: {"description": "O robô não respondeu em `GO2_REQUEST_TIMEOUT_S`."},
}

_UPLOAD_ERRORS: dict[int | str, dict[str, Any]] = {
    **_ERRORS,
    409: {"description": "Já há um envio em andamento, ou o nome já existe."},
    413: {
        "description": (
            "O arquivo, ou o WAV que iria ao robô, passa de `GO2_AUDIO_MAX_UPLOAD_MB`."
        )
    },
    415: {"description": "Não é WAV nem MP3, ou não decodifica."},
    422: {"description": "Nome inválido ou corpo sem o campo `file`."},
}

_UPLOAD_BODY: dict[str, Any] = {
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
                            "description": "WAV ou MP3 (detectado pelo conteúdo).",
                        },
                        "name": {
                            "type": "string",
                            "description": (
                                "Nome no robô (1–64 caracteres, sem `/`, `\\` nem "
                                "controle). Sem ele, o nome do arquivo sem extensão."
                            ),
                        },
                    },
                }
            }
        },
    }
}


@router.get(
    "/files",
    response_model=list[AudioFileResponse],
    responses=_ERRORS,
    summary="Lista os áudios guardados no robô",
)
async def list_files(robot: RobotDep) -> list[AudioFileResponse]:
    """`audio_list` do robô: `id`, `name` e o resto em `extra`."""
    files = await robot.audio.list_files()
    return [AudioFileResponse(id=f.id, name=f.name, extra=f.extra) for f in files]


@router.post(
    "/files",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=UploadAccepted,
    responses=_UPLOAD_ERRORS,
    openapi_extra=_UPLOAD_BODY,
    summary="Envia um WAV ou MP3 ao robô",
)
async def upload_file(request: Request, robot: RobotDep) -> UploadAccepted:
    """Valida, converte (MP3 → WAV 44,1 kHz) e envia em segundo plano.

    Um envio por vez. Os blocos ocupam o data channel do `move` e do `stop`
    por minutos num arquivo grande. Acompanhe em `GET /audio/uploads/{id}`.
    """
    hub = robot.audio

    async def read() -> UploadSource:
        return await StreamingUpload.read(
            request.headers, request.stream(), hub.max_upload_bytes
        )

    record = await hub.upload(read)
    return UploadAccepted(
        upload_id=record.upload_id, name=record.name, total_chunks=record.total_chunks
    )


@router.get(
    "/uploads/{upload_id}",
    response_model=UploadStatusResponse,
    responses={404: {"description": "Envio desconhecido (guardam-se os 20 últimos)."}},
    summary="Estado de um envio",
)
async def upload_status(upload_id: str, robot: RobotDep) -> UploadStatusResponse:
    """`uploading`, `done` ou `failed` (com o motivo em `error`)."""
    record = robot.audio.upload_status(upload_id)
    return UploadStatusResponse(
        state=record.state,
        name=record.name,
        sent_chunks=record.sent_chunks,
        total_chunks=record.total_chunks,
        file_id=record.file_id,
        error=record.error,
    )


@router.patch(
    "/files/{file_id}",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=AudioRenamedResponse,
    responses=_ERRORS,
    summary="Renomeia um áudio",
)
async def rename_file(
    file_id: str, body: AudioRenameRequest, robot: RobotDep
) -> AudioRenamedResponse:
    """Responde depois de o robô aceitar."""
    name = body.validated()
    await robot.audio.rename(file_id, name)
    return AudioRenamedResponse(id=file_id, name=name)


@router.delete(
    "/files/{file_id}",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=AudioAccepted,
    responses=_ERRORS,
    summary="Apaga um áudio",
)
async def delete_file(file_id: str, robot: RobotDep) -> AudioAccepted:
    """Responde depois de o robô aceitar."""
    await robot.audio.delete(file_id)
    return AudioAccepted()


@router.post(
    "/files/{file_id}/play",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=AudioAccepted,
    responses=_ERRORS,
    summary="Toca um áudio guardado",
)
async def play_file(file_id: str, robot: RobotDep) -> AudioAccepted:
    """Aceite do robô; não espera o som terminar."""
    await robot.audio.play(file_id)
    return AudioAccepted()


@router.post(
    "/pause",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=AudioAccepted,
    responses=_ERRORS,
    summary="Pausa a reprodução",
)
async def pause(robot: RobotDep) -> AudioAccepted:
    """Responde depois de o robô aceitar."""
    await robot.audio.pause()
    return AudioAccepted()


@router.post(
    "/resume",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=AudioAccepted,
    responses=_ERRORS,
    summary="Retoma a reprodução",
)
async def resume(robot: RobotDep) -> AudioAccepted:
    """Responde depois de o robô aceitar."""
    await robot.audio.resume()
    return AudioAccepted()


@router.get(
    "/play-mode",
    response_model=PlayModeResponse,
    responses=_ERRORS,
    summary="Lê o modo de reprodução",
)
async def get_play_mode(robot: RobotDep) -> PlayModeResponse:
    """Modo informado pelo robô."""
    return PlayModeResponse(mode=await robot.audio.get_play_mode())


@router.put(
    "/play-mode",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=PlayModeResponse,
    responses=_ERRORS,
    summary="Define o modo de reprodução",
)
async def set_play_mode(body: PlayModeRequest, robot: RobotDep) -> PlayModeResponse:
    """`single_cycle`, `no_cycle` ou `list_loop`. `list_loop` pode tocar sem fim."""
    await robot.audio.set_play_mode(body.mode)
    return PlayModeResponse(mode=body.mode)


@router.post(
    "/silence",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=AudioAccepted,
    responses=_ERRORS,
    summary="Cala o robô: pausa o hub e para o alto-falante",
)
async def silence(robot: RobotDep) -> AudioAccepted:
    """Pausa o hub e para o alto-falante (F-007). Não mexe no movimento."""
    await robot.audio.silence()
    return AudioAccepted()


@router.get(
    "/player",
    response_model=PlayerStateResponse,
    summary="Último estado do player do robô, cru",
)
async def player(robot: RobotDep) -> PlayerStateResponse:
    """Do tópico `AUDIO_HUB_PLAY_STATE`, sem falar com o robô."""
    reading = robot.audio.player()
    return PlayerStateResponse(data=reading.data, age_s=reading.age_s)
