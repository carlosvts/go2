"""Corpos de request da API (entrada), validados na construção pelo pydantic."""

from app.requests.gesture import GestureRequest
from app.requests.move import MoveRequest
from app.requests.posture import PostureRequest
from app.requests.speed import SpeedLevelRequest

__all__ = [
    "GestureRequest",
    "MoveRequest",
    "PostureRequest",
    "SpeedLevelRequest",
]
