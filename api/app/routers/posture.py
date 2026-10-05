"""Grupo 4.1 — postura (`docs/arquitetura_go2_api.md`)."""

from fastapi import APIRouter, status

from app.dependencies import RobotDep
from app.requests import PostureRequest
from app.responses import CommandAccepted

router = APIRouter(prefix="/commands", tags=["commands"])


@router.post(
    "/posture",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=CommandAccepted,
    summary="Muda a postura do robô",
)
async def set_posture(body: PostureRequest, robot: RobotDep) -> CommandAccepted:
    """Despacha a postura, cancelando antes qualquer movimento em curso."""
    await robot.execute(body.cmd)
    return CommandAccepted(cmd=body.cmd.sport_cmd)
