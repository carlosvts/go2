"""Estado da conexão com o robô, como é publicado aos consumidores."""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import ClassVar

log = logging.getLogger(__name__)


class ConnectionState(StrEnum):
    """Estado publicado da conexão.

    É informativo: quem decide se um comando sai ou leva `503` continua sendo
    :attr:`~app.robot.link.RobotLink.is_connected`.
    """

    connected = "connected"
    disconnected = "disconnected"
    # A conexão caiu (ou ainda não abriu) e a API está tentando de novo.
    reconnecting = "reconnecting"


@dataclass(frozen=True)
class ConnectionSnapshot:
    """Estado atual e o momento (UTC) da última transição."""

    state: ConnectionState
    since: datetime


ConnectionListener = Callable[[dict[str, str]], None]
"""Recebe `{"state": <ConnectionState>, "reason": <pc.connectionState>}`."""


def _utc_now() -> datetime:
    return datetime.now(UTC)


class ConnectionStateTracker:
    """Guarda o estado da conexão e avisa os ouvintes a cada transição.

    Só transições reais são publicadas: eventos repetidos (`failed` seguido
    de `closed`, por exemplo) geram uma mensagem só. Não há debounce — uma
    oscilação rápida publica todas as transições.
    """

    _PEER_STATES: ClassVar[dict[str, ConnectionState]] = {
        "connected": ConnectionState.connected,
        "disconnected": ConnectionState.disconnected,
        "failed": ConnectionState.disconnected,
        "closed": ConnectionState.disconnected,
    }
    """`RTCPeerConnection.connectionState` → estado publicado. Os transitórios
    (`new`, `connecting`) não mudam nada."""

    def __init__(self, clock: Callable[[], datetime] = _utc_now) -> None:
        """Começa `disconnected` — inclusive quando a conexão da subida falha.

        Args:
            clock: Relógio em UTC (injetável para testes determinísticos).
        """
        self._clock = clock
        self._state = ConnectionState.disconnected
        self._since = clock()
        self._listeners: list[ConnectionListener] = []

    @property
    def current(self) -> ConnectionSnapshot:
        """Estado atual e o momento da última transição."""
        return ConnectionSnapshot(self._state, self._since)

    def subscribe(self, listener: ConnectionListener) -> None:
        """Registra `listener` para receber as próximas transições."""
        self._listeners.append(listener)

    def on_peer_state(self, peer_state: str) -> None:
        """Traduz um `connectionState` do aiortc e publica se o estado mudar."""
        state = self._PEER_STATES.get(peer_state)
        if state is not None:
            self.update(state, reason=peer_state)

    def update(self, state: ConnectionState, *, reason: str) -> None:
        """Muda para `state` e avisa os ouvintes; repetição é ignorada.

        Args:
            state: Novo estado.
            reason: `connectionState` do peer que causou a transição.
        """
        if state is self._state:
            return
        self._state = state
        self._since = self._clock()
        log.info("Conexão com o Go2: %s (%s).", state.value, reason)
        payload = {"state": state.value, "reason": reason}
        for listener in self._listeners:
            try:
                listener(payload)
            except Exception:
                # Um ouvinte com defeito não pode impedir os outros de saberem.
                log.exception("❌ Falha num ouvinte do estado da conexão.")
