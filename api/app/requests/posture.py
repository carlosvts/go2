"""Corpo de `POST /commands/posture` (grupo 4.1 de `docs/arquitetura_go2_api.md`)."""

from enum import auto

from pydantic import BaseModel

from app.robot.commands import SportCommand


class PostureRequest(BaseModel):
    """Pedido de mudança de postura. Comando fora do enum é rejeitado (422)."""

    class Posture(SportCommand):
        """Posturas aceitas, como aparecem no corpo da request.

        Gestos ficam em :class:`~app.requests.gesture.GestureRequest`; os
        "tricks" (`front_flip`, ...) ainda não existem — grupo 4.2 da
        `docs/arquitetura_go2_api.md`.
        """

        stand_up = auto()
        stand_down = auto()
        sit = auto()
        rise_sit = auto()
        balance_stand = auto()
        recovery_stand = auto()
        damp = auto()

    cmd: Posture
