"""Corpo de `POST /commands/gesture` (grupo 4.2 de `docs/arquitetura_go2_api.md`)."""

from enum import auto

from pydantic import BaseModel

from app.robot.commands import SportCommand


class GestureRequest(BaseModel):
    """Pedido de gesto. Comando fora do enum é rejeitado (422).

    Só os gestos de baixo risco físico. Os "tricks" (`front_flip`,
    `handstand`, ...) ficam de fora: exigem flag de confirmação e teste físico
    antes, ver `docs/arquitetura_go2_api.md` seção 4.2.
    """

    class Gesture(SportCommand):
        """Gestos aceitos, como aparecem no corpo da request."""

        hello = auto()
        stretch = auto()
        finger_heart = auto()
        wiggle_hips = auto()
        content = auto()
        dance1 = auto()
        dance2 = auto()
        scrape = auto()
        pose = auto()

    cmd: Gesture
