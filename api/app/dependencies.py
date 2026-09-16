"""Dependências compartilhadas pelos routers."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request

from app.config import Settings, get_settings
from app.robot import RobotConnection


def get_robot(request: Request) -> RobotConnection:
    return request.app.state.robot


RobotDep = Annotated[RobotConnection, Depends(get_robot)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
