"""Dependências compartilhadas pelos routers (injeção via `Depends`)."""

from typing import Annotated

from fastapi import Depends, Request

from app.config import Settings
from app.requests.move import MoveRequest
from app.robot.commands import MoveCommand, MoveLimits
from app.robot.service import Go2Robot


def get_robot(request: Request) -> Go2Robot:
    """Devolve o robô único, criado no lifespan da app."""
    robot: Go2Robot = request.app.state.robot
    return robot


def get_settings(request: Request) -> Settings:
    """Devolve a configuração com que a app foi criada."""
    settings: Settings = request.app.state.settings
    return settings


RobotDep = Annotated[Go2Robot, Depends(get_robot)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


def get_move_limits(settings: SettingsDep) -> MoveLimits:
    """Monta os tetos de movimento a partir da configuração."""
    return MoveLimits(
        max_vx=settings.max_vx,
        max_vy=settings.max_vy,
        max_vyaw=settings.max_vyaw,
        max_duration_s=settings.move_max_duration_s,
    )


MoveLimitsDep = Annotated[MoveLimits, Depends(get_move_limits)]


def get_move_command(body: MoveRequest, limits: MoveLimitsDep) -> MoveCommand:
    """Constrói o :class:`MoveCommand`, que se recusa a existir fora dos tetos.

    Um :class:`~app.exceptions.InvalidCommandError` levantado aqui vira `422`
    em :mod:`app.error_handlers`; o endpoint recebe sempre um comando válido.
    """
    return body.to_command(limits)


MoveCommandDep = Annotated[MoveCommand, Depends(get_move_command)]
