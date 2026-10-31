"""Movimento contínuo: `POST /commands/move` e `POST /commands/stop`."""

from fastapi import APIRouter, status

from app.dependencies import MoveCommandDep, RobotDep
from app.responses import CommandAccepted

router = APIRouter(prefix="/commands", tags=["commands"])


@router.post(
    "/move",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=CommandAccepted,
    summary="Move o robô por uma janela de tempo",
)
async def move(command: MoveCommandDep, robot: RobotDep) -> CommandAccepted:
    """Reenvia `Move` a `GO2_MOVE_RATE_HZ` durante `duration_s` e então para.

    O corpo é validado antes de chegar aqui: `command` já respeita os tetos
    configurados (`422` caso contrário). Sem lease nesta versão: um `move`
    novo substitui o que estiver em curso.
    """
    await robot.start_move(command)
    return CommandAccepted(cmd="Move")


@router.post(
    "/stop",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=CommandAccepted,
    summary="Para o movimento imediatamente",
)
async def stop(robot: RobotDep) -> CommandAccepted:
    """Cancela o reenvio em curso e manda `StopMove`.

    Para desenergizar as juntas, use `POST /commands/posture` com `damp`.
    """
    await robot.stop()
    return CommandAccepted(cmd="StopMove")
