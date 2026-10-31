"""Desvio de obstáculo: `PUT` e `GET /safety/obstacle-avoidance`."""

from fastapi import APIRouter, status

from app.dependencies import RobotDep
from app.requests import ObstacleAvoidanceRequest
from app.responses import CommandAccepted, ObstacleAvoidanceResponse

router = APIRouter(prefix="/safety", tags=["safety"])


@router.put(
    "/obstacle-avoidance",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=CommandAccepted,
    summary="Liga ou desliga o desvio de obstáculo",
)
async def set_obstacle_avoidance(
    body: ObstacleAvoidanceRequest, robot: RobotDep
) -> CommandAccepted:
    """Despacha o pedido sem esperar confirmação; confira com o `GET`.

    Ligar o desvio **não garante** que `POST /commands/move` seja filtrado:
    a API anda pelo `SPORT_CMD["Move"]`, e o que o serviço de desvio
    comprovadamente intercepta é o canal do controle (dossiê 12.1).
    """
    await robot.set_obstacle_avoidance(enabled=body.enabled)
    return CommandAccepted(cmd="ObstacleAvoidance")


@router.get(
    "/obstacle-avoidance",
    response_model=ObstacleAvoidanceResponse,
    summary="Lê se o desvio de obstáculo está ligado",
)
async def get_obstacle_avoidance(robot: RobotDep) -> ObstacleAvoidanceResponse:
    """Espera a resposta do robô.

    Sujeito a `504` se ele não responder dentro de `GO2_REQUEST_TIMEOUT_S`.
    """
    return ObstacleAvoidanceResponse.from_reading(await robot.get_obstacle_avoidance())
