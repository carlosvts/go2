"""Grupo 4.2 — gestos (`docs/arquitetura_go2_api.md`).

Só os gestos de baixo risco físico; os "tricks" entram depois, em endpoint
próprio e com confirmação explícita.
"""

from __future__ import annotations

from fastapi import APIRouter, status

from app.dependencies import RobotDep
from app.models import CommandAccepted, GestureRequest

router = APIRouter(prefix="/commands", tags=["commands"])


@router.post(
    "/gesture",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=CommandAccepted,
    summary="Executa um gesto",
)
async def gesture(body: GestureRequest, robot: RobotDep) -> CommandAccepted:
    """Despacha o gesto e responde na hora — a duração de cada um é decidida
    pelo robô, e a API não acompanha o fim da execução.

    Como na postura, um movimento em curso é cancelado antes: o robô não anda e
    gesticula ao mesmo tempo.
    """
    await robot.gesture(body.cmd.sport_cmd)
    return CommandAccepted(cmd=body.cmd.sport_cmd)
