"""Mensagem de saída comum aos clientes WebSocket dos streams."""

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class ClientMessage:
    """Próxima coisa a fazer com o WebSocket do cliente."""

    kind: Literal["bytes", "text", "close", "gone"]
    data: bytes | str | None = None
    code: int | None = None
    reason: str | None = None
