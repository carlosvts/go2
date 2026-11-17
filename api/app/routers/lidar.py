"""`/ws/lidar`: nuvem de pontos do LiDAR em frames binários (F-001).

Formato do frame e códigos de fechamento: `specs/contracts/ws-lidar.md`.
"""

import asyncio
import contextlib
import logging
from typing import TYPE_CHECKING

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

if TYPE_CHECKING:
    from app.robot.lidar import LidarClient
    from app.robot.service import Go2Robot

log = logging.getLogger(__name__)

router = APIRouter(tags=["streams"])

CLOSE_TRY_AGAIN_LATER = 1013


async def _watch_disconnect(websocket: WebSocket, client: "LidarClient") -> None:
    """Ignora o que o cliente manda e avisa quando ele desconecta."""
    try:
        while True:
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect":
                break
    finally:
        client.mark_gone()


@router.websocket("/ws/lidar")
async def lidar_stream(websocket: WebSocket) -> None:
    """Envia o estado da conexão (texto) e a nuvem de pontos (binário)."""
    robot: Go2Robot = websocket.app.state.robot
    # Aceita antes de recusar: fechar sem aceitar vira HTTP 403 no Starlette.
    await websocket.accept()
    client = robot.lidar.add_client()
    if client is None:
        await websocket.close(CLOSE_TRY_AGAIN_LATER, "max_clients")
        return
    watcher = asyncio.create_task(_watch_disconnect(websocket, client))
    try:
        while True:
            message = await client.next()
            if message.kind == "gone":
                break
            if message.kind == "close":
                await websocket.close(message.code or 1000, message.reason or "")
                break
            if isinstance(message.data, bytes):
                await websocket.send_bytes(message.data)
            elif isinstance(message.data, str):
                await websocket.send_text(message.data)
    except (WebSocketDisconnect, RuntimeError):
        log.debug("Cliente de /ws/lidar saiu durante o envio.")
    finally:
        robot.lidar.remove_client(client)
        watcher.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await watcher
