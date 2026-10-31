"""Grupo 4.2 — gestos (`docs/arquitetura_go2_api.md`)."""

from fastapi import APIRouter, status

from app.dependencies import RobotDep
from app.requests import GestureRequest
from app.responses import CommandAccepted

router = APIRouter(prefix="/commands", tags=["commands"])


@router.post(
    "/gesture",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=CommandAccepted,
    summary="Executa um gesto",
)
async def perform_gesture(body: GestureRequest, robot: RobotDep) -> CommandAccepted:
    """Despacha o gesto e responde na hora.

    A duração de cada gesto é decidida pelo robô, e a API não acompanha o fim
    da execução. Como na postura, um movimento em curso é cancelado antes: o
    robô não anda e gesticula ao mesmo tempo.
    """
    await robot.execute(body.cmd)
    return CommandAccepted(cmd=body.cmd.sport_cmd)
