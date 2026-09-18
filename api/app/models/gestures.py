"""Schemas do grupo 4.2 — gestos.

Só os gestos de baixo risco físico. Os "tricks" (`front_flip`, `handstand`,
...) ficam de fora: exigem flag de confirmação e teste físico antes, ver
`docs/arquitetura_go2_api.md` seção 4.2.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel
from unitree_webrtc_connect import SPORT_CMD


class GestureCommand(str, Enum):
    """Gestos, como aparecem no corpo da request."""

    hello = "hello"
    stretch = "stretch"
    finger_heart = "finger_heart"
    wiggle_hips = "wiggle_hips"
    content = "content"
    dance1 = "dance1"
    dance2 = "dance2"
    scrape = "scrape"
    pose = "pose"

    @property
    def sport_cmd(self) -> str:
        """Chave correspondente em `SPORT_CMD`."""
        return _SPORT_CMD_NAMES[self]


_SPORT_CMD_NAMES: dict[GestureCommand, str] = {
    GestureCommand.hello: "Hello",
    GestureCommand.stretch: "Stretch",
    GestureCommand.finger_heart: "FingerHeart",
    GestureCommand.wiggle_hips: "WiggleHips",
    GestureCommand.content: "Content",
    GestureCommand.dance1: "Dance1",
    GestureCommand.dance2: "Dance2",
    GestureCommand.scrape: "Scrape",
    GestureCommand.pose: "Pose",
}

# Falha na importação, não no primeiro comando, se a lib renomear algo.
assert set(_SPORT_CMD_NAMES) == set(GestureCommand)
assert all(nome in SPORT_CMD for nome in _SPORT_CMD_NAMES.values())


class GestureRequest(BaseModel):
    cmd: GestureCommand
