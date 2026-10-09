"""App factory da go2-api.

Suba com `uvicorn app.main:create_app --factory`. Não há instância global de
`app`: importar este módulo não lê configuração nem cria conexões.
"""

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import __version__
from app.config import Settings
from app.error_handlers import ErrorHandlers
from app.robot.ports import ConnectionFactory
from app.robot.service import Go2Robot
from app.routers import gesture, movement, posture, speed
from app.routers import status as status_router

log = logging.getLogger(__name__)


class RobotLifespan:
    """Cria o robô na subida da app e o encerra na descida."""

    def __init__(
        self,
        settings: Settings,
        connection_factory: ConnectionFactory | None = None,
    ) -> None:
        """Recebe a configuração e, opcionalmente, uma fábrica de conexões."""
        self._settings = settings
        self._connection_factory = connection_factory

    @asynccontextmanager
    async def __call__(self, app: FastAPI) -> AsyncIterator[None]:
        """Disponibiliza `app.state.robot` durante a vida da app."""
        robot = Go2Robot.from_settings(self._settings, self._connection_factory)
        app.state.robot = robot
        await self._connect(robot)
        keeper = self._start_keeper(robot)
        try:
            yield
        finally:
            if keeper is not None:
                keeper.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await keeper
            await robot.disconnect()

    def _start_keeper(self, robot: Go2Robot) -> asyncio.Task[None] | None:
        """Liga a reconexão automática, a menos que a API suba sem conectar."""
        if not self._settings.connect_on_startup:
            return None
        return asyncio.create_task(
            robot.keep_connected(self._settings.reconnect_interval_s)
        )

    async def _connect(self, robot: Go2Robot) -> None:
        """Conecta na subida, sem impedir a API de subir se falhar.

        Subir mesmo assim é proposital: com o robô desligado a API ainda
        precisa responder `GET /status` com `connected: false`. As tentativas
        seguintes ficam por conta de
        :meth:`~app.robot.service.Go2Robot.keep_connected`.
        """
        if not self._settings.connect_on_startup:
            log.warning("GO2_CONNECT_ON_STARTUP=false — subindo sem conectar.")
            return
        try:
            await robot.connect()
        except Exception:
            log.exception("❌ Não foi possível conectar ao robô na inicialização.")


def create_app(
    settings: Settings | None = None,
    *,
    connection_factory: ConnectionFactory | None = None,
) -> FastAPI:
    """Monta a aplicação FastAPI.

    Args:
        settings: Configuração. Se omitida, é lida do ambiente / `.env`.
        connection_factory: Fábrica de conexões com o robô. Existe para os
            testes injetarem uma conexão falsa; em produção fica omitida.
    """
    resolved = settings if settings is not None else Settings()
    app = FastAPI(
        title="go2-api",
        version=__version__,
        summary="Dona única da conexão WebRTC com o Unitree Go2.",
        lifespan=RobotLifespan(resolved, connection_factory),
    )
    app.state.settings = resolved
    ErrorHandlers.register(app)
    app.include_router(status_router.router)
    app.include_router(posture.router)
    app.include_router(gesture.router)
    app.include_router(movement.router)
    app.include_router(speed.router)
    return app
