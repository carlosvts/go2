"""Schemas do grupo 4.1 — postura e movimento."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field
from unitree_webrtc_connect import SPORT_CMD


class PostureCommand(str, Enum):
    """Comandos de postura, como aparecem no corpo da request.

    Gestos (`hello`, `stretch`, ...) ficam em `app/models/gestures.py`; os
    "tricks" (`front_flip`, ...) ainda não existem — grupo 4.2 da
    `docs/arquitetura_go2_api.md`.
    """

    stand_up = "stand_up"
    stand_down = "stand_down"
    sit = "sit"
    rise_sit = "rise_sit"
    balance_stand = "balance_stand"
    recovery_stand = "recovery_stand"
    damp = "damp"

    @property
    def sport_cmd(self) -> str:
        """Chave correspondente em `SPORT_CMD`."""
        return _SPORT_CMD_NAMES[self]


_SPORT_CMD_NAMES: dict[PostureCommand, str] = {
    PostureCommand.stand_up: "StandUp",
    PostureCommand.stand_down: "StandDown",
    PostureCommand.sit: "Sit",
    PostureCommand.rise_sit: "RiseSit",
    PostureCommand.balance_stand: "BalanceStand",
    PostureCommand.recovery_stand: "RecoveryStand",
    PostureCommand.damp: "Damp",
}

# Falha na importação, não no primeiro comando, se a lib renomear algo.
assert set(_SPORT_CMD_NAMES) == set(PostureCommand)
assert all(nome in SPORT_CMD for nome in _SPORT_CMD_NAMES.values())


class PostureRequest(BaseModel):
    cmd: PostureCommand


class MoveRequest(BaseModel):
    """Velocidades no referencial do robô.

    Os tetos configuráveis (`GO2_MAX_VX`/`GO2_MAX_VY`/`GO2_MAX_VYAW` e
    `GO2_MOVE_MAX_DURATION_S`) são aplicados no router, que devolve 422 quando
    o pedido os ultrapassa.
    """

    vx: float = Field(description="Velocidade para frente, em m/s.")
    vy: float = Field(description="Velocidade lateral, em m/s.")
    vyaw: float = Field(description="Velocidade angular, em rad/s.")
    duration_s: float = Field(
        gt=0, description="Por quanto tempo a API reenvia o comando ao robô."
    )


class SpeedLevelRequest(BaseModel):
    level: int


class SpeedLevelResponse(BaseModel):
    level: int | None = Field(
        description=(
            "Nível informado pelo robô. Vem `null` quando a resposta não pôde "
            "ser interpretada — consulte `raw` nesse caso."
        )
    )
    raw: Any = Field(
        default=None,
        description="Resposta crua do robô, sem interpretação.",
    )


class CommandAccepted(BaseModel):
    """Resposta de `202 Accepted`.

    A API confirma que aceitou e despachou o comando — não que o robô terminou
    de executá-lo fisicamente (`docs/arquitetura_go2_api.md` seção 2).
    """

    accepted: bool = True
    cmd: str
