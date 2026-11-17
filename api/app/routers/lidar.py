"""`/ws/lidar`: nuvem de pontos do LiDAR em frames binários (F-001).

Formato do frame e códigos de fechamento: `specs/contracts/ws-lidar.md`.
"""

from typing import TYPE_CHECKING

from fastapi import APIRouter, WebSocket

from app.routers.streaming import refuse, serve

if TYPE_CHECKING:
    from app.robot.service import Go2Robot

router = APIRouter(tags=["streams"])


@router.websocket("/ws/lidar")
async def lidar_stream(websocket: WebSocket) -> None:
    """Envia o estado da conexão (texto) e a nuvem de pontos (binário)."""
    robot: Go2Robot = websocket.app.state.robot
    client = robot.lidar.add_client()
    if client is None:
        await refuse(websocket)
        return
    await websocket.accept()
    await serve(websocket, client, lambda: robot.lidar.remove_client(client))
