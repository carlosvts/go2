"""Corpos de resposta da API (saída)."""

from app.responses.capabilities import CapabilitiesResponse, Capability
from app.responses.command import CommandAccepted
from app.responses.safety import ObstacleAvoidanceResponse
from app.responses.speed import SpeedLevelResponse
from app.responses.status import StatusResponse

__all__ = [
    "CapabilitiesResponse",
    "Capability",
    "CommandAccepted",
    "ObstacleAvoidanceResponse",
    "SpeedLevelResponse",
    "StatusResponse",
]
