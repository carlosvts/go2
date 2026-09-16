"""Grupo 4.1 — postura e movimento (`docs/arquitetura_go2_api.md`).

Wrapper HTTP fino sobre os comandos que o `robot_control` já emitia. Sem lease,
sem fila e sem token nesta versão: cada endpoint despacha o comando direto.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from app.dependencies import RobotDep, SettingsDep
from app.models import (
    CommandAccepted,
    MoveRequest,
    PostureRequest,
    SpeedLevelRequest,
    SpeedLevelResponse,
)

router = APIRouter(prefix="/commands", tags=["commands"])


@router.post(
    "/posture",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=CommandAccepted,
    summary="Muda a postura do robô",
)
async def set_posture(body: PostureRequest, robot: RobotDep) -> CommandAccepted:
    await robot.posture(body.cmd.sport_cmd)
    return CommandAccepted(cmd=body.cmd.sport_cmd)


@router.post(
    "/move",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=CommandAccepted,
    summary="Move o robô por uma janela de tempo",
)
async def move(
    body: MoveRequest, robot: RobotDep, settings: SettingsDep
) -> CommandAccepted:
    """A API reenvia o comando internamente a `GO2_MOVE_RATE_HZ` durante
    `duration_s` e então manda `StopMove`.

    Sem lease nesta versão: um `move` novo substitui o que estiver em curso.
    """
    excedidos = [
        nome
        for nome, valor, teto in (
            ("vx", body.vx, settings.max_vx),
            ("vy", body.vy, settings.max_vy),
            ("vyaw", body.vyaw, settings.max_vyaw),
        )
        if abs(valor) > teto
    ]
    if excedidos:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Fora do limite configurado: {', '.join(excedidos)}.",
        )
    if body.duration_s > settings.move_max_duration_s:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                f"duration_s excede GO2_MOVE_MAX_DURATION_S "
                f"({settings.move_max_duration_s}s)."
            ),
        )

    await robot.start_move(body.vx, body.vy, body.vyaw, body.duration_s)
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


@router.put(
    "/speed",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=CommandAccepted,
    summary="Define o nível de velocidade",
)
async def set_speed(body: SpeedLevelRequest, robot: RobotDep) -> CommandAccepted:
    await robot.set_speed_level(body.level)
    return CommandAccepted(cmd="SpeedLevel")


@router.get(
    "/speed",
    response_model=SpeedLevelResponse,
    summary="Lê o nível de velocidade do robô",
)
async def get_speed(robot: RobotDep) -> SpeedLevelResponse:
    """Único endpoint desta versão que espera resposta do robô — sujeito a
    `504` se ele não responder dentro de `GO2_REQUEST_TIMEOUT_S`."""
    level, raw = await robot.get_speed_level()
    return SpeedLevelResponse(level=level, raw=raw)
