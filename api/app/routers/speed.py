"""Nível de velocidade: `PUT` e `GET /commands/speed`."""

from fastapi import APIRouter, status

from app.dependencies import RobotDep
from app.requests import SpeedLevelRequest
from app.responses import CommandAccepted, SpeedLevelResponse

router = APIRouter(prefix="/commands", tags=["commands"])


@router.put(
    "/speed",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=CommandAccepted,
    summary="Define o nível de velocidade",
)
async def set_speed(body: SpeedLevelRequest, robot: RobotDep) -> CommandAccepted:
    """Despacha o nível de velocidade sem esperar confirmação."""
    await robot.set_speed_level(body.level)
    return CommandAccepted(cmd="SpeedLevel")


@router.get(
    "/speed",
    response_model=SpeedLevelResponse,
    summary="Lê o nível de velocidade do robô",
)
async def get_speed(robot: RobotDep) -> SpeedLevelResponse:
    """Único endpoint desta versão que espera resposta do robô.

    Sujeito a `504` se ele não responder dentro de `GO2_REQUEST_TIMEOUT_S`.
    """
    return SpeedLevelResponse.from_reading(await robot.get_speed_level())
