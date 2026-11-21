"""Laço comum dos WebSockets de stream (`/ws/lidar`, `/ws/telemetry`)."""

import asyncio
import contextlib
import logging
from collections.abc import Callable
from typing import Protocol

from fastapi import WebSocket, WebSocketDisconnect

from app.robot.clients import ClientMessage

log = logging.getLogger(__name__)

CLOSE_TRY_AGAIN_LATER = 1013


class StreamClient(Protocol):
    """Saída de um cliente: o que enviar a seguir e como saber que ele saiu."""

    async def next(self) -> ClientMessage:
        """Espera a próxima mensagem a enviar."""

    def mark_gone(self) -> None:
        """O cliente desconectou por conta própria."""


async def _watch_disconnect(websocket: WebSocket, client: StreamClient) -> None:
    """Ignora o que o cliente manda e avisa quando ele desconecta."""
    try:
        while True:
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect":
                break
    finally:
        client.mark_gone()


async def refuse(websocket: WebSocket) -> None:
    """Recusa por limite: aceita antes, senão o Starlette responde HTTP 403."""
    await websocket.accept()
    await websocket.close(CLOSE_TRY_AGAIN_LATER, "max_clients")


async def serve(
    websocket: WebSocket, client: StreamClient, release: Callable[[], None]
) -> None:
    """Envia o que o cliente tiver até ele sair ou a api fechá-lo.

    O WebSocket já precisa estar aceito. `release` tira o cliente do stream.
    """
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
        log.debug("Cliente saiu durante o envio.")
    finally:
        release()
        watcher.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await watcher
