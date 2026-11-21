"""Lanterna, LED e volume: `/device/brightness`, `/device/volume`, `/device/led`.

Toda rota espera a resposta do robô (F-005). `202` = o robô **aceitou**
(`header.status.code == 0`), não que alguém viu a luz ou ouviu o som. Em
`502` e `504` o estado do robô é desconhecido: confira com o `GET`. Estas
rotas não entram no `/capabilities`.
"""

from typing import Any

from fastapi import APIRouter, status

from app.dependencies import RobotDep, SettingsDep
from app.requests import DeviceLevelRequest, LedRequest
from app.responses import DeviceLevelResponse, LedResponse

router = APIRouter(prefix="/device", tags=["device"])

_ERRORS: dict[int | str, dict[str, Any]] = {
    502: {"description": "O robô recusou (código ≠ 0) ou respondeu algo ilegível."},
    503: {"description": "Sem conexão com o robô."},
    504: {"description": "O robô não respondeu em `GO2_REQUEST_TIMEOUT_S`."},
}


@router.put(
    "/brightness",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=DeviceLevelResponse,
    responses=_ERRORS,
    summary="Define o brilho da lanterna",
)
async def set_brightness(
    body: DeviceLevelRequest, robot: RobotDep, settings: SettingsDep
) -> DeviceLevelResponse:
    """Responde depois de o robô aceitar; até `GO2_MAX_BRIGHTNESS`."""
    level = body.within(settings.max_brightness, "GO2_MAX_BRIGHTNESS")
    await robot.device.set_brightness(level)
    return DeviceLevelResponse(level=level)


@router.get(
    "/brightness",
    response_model=DeviceLevelResponse,
    responses=_ERRORS,
    summary="Lê o brilho da lanterna",
)
async def get_brightness(robot: RobotDep) -> DeviceLevelResponse:
    """Nível guardado no robô."""
    return DeviceLevelResponse(level=await robot.device.get_brightness())


@router.put(
    "/volume",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=DeviceLevelResponse,
    responses=_ERRORS,
    summary="Define o volume do alto-falante",
)
async def set_volume(
    body: DeviceLevelRequest, robot: RobotDep, settings: SettingsDep
) -> DeviceLevelResponse:
    """Responde depois de o robô aceitar; até `GO2_MAX_VOLUME`."""
    level = body.within(settings.max_volume, "GO2_MAX_VOLUME")
    await robot.device.set_volume(level)
    return DeviceLevelResponse(level=level)


@router.get(
    "/volume",
    response_model=DeviceLevelResponse,
    responses=_ERRORS,
    summary="Lê o volume do alto-falante",
)
async def get_volume(robot: RobotDep) -> DeviceLevelResponse:
    """Nível guardado no robô."""
    return DeviceLevelResponse(level=await robot.device.get_volume())


@router.put(
    "/led",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=LedResponse,
    responses=_ERRORS,
    summary="Mostra uma cor no LED por um tempo",
)
async def set_led(
    body: LedRequest, robot: RobotDep, settings: SettingsDep
) -> LedResponse:
    """Responde depois de o robô aceitar. Não há leitura da cor."""
    command = body.to_command(settings.led_max_duration_s)
    await robot.device.set_led(command)
    return LedResponse(
        color=command.color,
        duration_s=command.duration_s,
        flash_cycle_ms=command.flash_cycle_ms,
    )
