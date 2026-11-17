"""`/ws/telemetry`: telemetria do LiDAR em frames de texto JSON (F-002).

Tópicos, métricas e códigos de fechamento: `specs/contracts/ws-telemetry.md`.
"""

from typing import TYPE_CHECKING

from fastapi import APIRouter, WebSocket

from app.routers.streaming import refuse, serve

if TYPE_CHECKING:
    from app.robot.service import Go2Robot

router = APIRouter(tags=["streams"])


@router.websocket("/ws/telemetry")
async def telemetry_stream(websocket: WebSocket) -> None:
    """Envia `connection`, `lidar_metrics`, `lidar_pose` e `lidar_state`."""
    robot: Go2Robot = websocket.app.state.robot
    client = robot.lidar.add_telemetry_client()
    if client is None:
        await refuse(websocket)
        return
    await websocket.accept()
    await serve(websocket, client, lambda: robot.lidar.remove_telemetry_client(client))
