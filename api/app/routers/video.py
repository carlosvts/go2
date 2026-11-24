"""`/ws/video`: câmera frontal em frames binários JPEG (F-003).

Formato do frame, tópicos de texto e códigos de fechamento:
`specs/contracts/ws-video.md`.
"""

from typing import TYPE_CHECKING

from fastapi import APIRouter, WebSocket

from app.routers.streaming import refuse, serve

if TYPE_CHECKING:
    from app.robot.service import Go2Robot

router = APIRouter(tags=["streams"])


@router.websocket("/ws/video")
async def video_stream(websocket: WebSocket) -> None:
    """Envia o estado da conexão e da câmera (texto) e os quadros (binário)."""
    robot: Go2Robot = websocket.app.state.robot
    client = robot.video.add_client()
    if client is None:
        await refuse(websocket)
        return
    await websocket.accept()
    await serve(websocket, client, lambda: robot.video.remove_client(client))
