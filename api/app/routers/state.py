"""`/ws/state`: estado do robô e erros ativos em frames de texto JSON (F-004).

Tópicos, ordem, taxa e códigos de fechamento: `specs/contracts/ws-state.md`.
"""

from typing import TYPE_CHECKING

from fastapi import APIRouter, WebSocket

from app.routers.streaming import refuse, serve

if TYPE_CHECKING:
    from app.robot.service import Go2Robot

router = APIRouter(tags=["streams"])


@router.websocket("/ws/state")
async def state_stream(websocket: WebSocket) -> None:
    """Envia `connection`, as seções do `/status` e `errors`."""
    robot: Go2Robot = websocket.app.state.robot
    stream = robot.state_stream
    client = stream.add_client()
    if client is None:
        await refuse(websocket)
        return
    await websocket.accept()
    await serve(websocket, client, lambda: stream.remove_client(client))
