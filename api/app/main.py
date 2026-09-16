"""App factory da go2-api."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from app.config import Settings, get_settings
from app.robot import RobotConnection, RobotTimeoutError, RobotUnavailableError
from app.routers import posture, status as status_router

log = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        robot = RobotConnection(settings)
        app.state.robot = robot

        if settings.connect_on_startup:
            try:
                await robot.connect()
            except Exception:
                # Subir mesmo assim é proposital: com o robô desligado a API
                # ainda precisa responder `GET /status` com `connected: false`.
                # Não há reconexão automática — ver `app/robot.py`.
                log.exception("❌ Não foi possível conectar ao robô na inicialização.")
        else:
            log.warning("GO2_CONNECT_ON_STARTUP=false — subindo sem conectar.")

        try:
            yield
        finally:
            await robot.disconnect()

    app = FastAPI(
        title="go2-api",
        version="0.1.0",
        summary="Dona única da conexão WebRTC com o Unitree Go2.",
        lifespan=lifespan,
    )

    @app.exception_handler(RobotUnavailableError)
    async def _unavailable(_: Request, exc: RobotUnavailableError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"detail": str(exc)},
        )

    @app.exception_handler(RobotTimeoutError)
    async def _timeout(_: Request, exc: RobotTimeoutError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            content={"detail": str(exc)},
        )

    app.include_router(status_router.router)
    app.include_router(posture.router)
    return app


app = create_app()
