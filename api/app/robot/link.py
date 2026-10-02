"""Ciclo de vida da conexão WebRTC com o robô."""

import contextlib

from app.exceptions import RobotUnavailableError
from app.robot.ports import ConnectionFactory, PubSub, WebRTCConnection

NOT_CONNECTED_MESSAGE = "❌ Sem conexão com o robô."


class RobotLink:
    """Dona da conexão: abre, fecha e informa se ela está viva.

    O WebRTC é ponto-a-ponto — só existe uma conexão por vez com o robô —, então
    esta classe é instanciada uma única vez por processo. Não há reconexão
    automática: uma queda só se resolve reiniciando a API (decisão do MVP).
    """

    def __init__(self, factory: ConnectionFactory) -> None:
        """Recebe a fábrica de conexões (injeção de dependência)."""
        self._factory = factory
        self._connection: WebRTCConnection | None = None

    async def connect(self) -> None:
        """Cria e abre a conexão; só a guarda se a abertura der certo."""
        connection = self._factory()
        await connection.connect()
        self._connection = connection

    async def disconnect(self) -> None:
        """Encerra a conexão, ignorando falhas de encerramento."""
        connection, self._connection = self._connection, None
        if connection is not None:
            with contextlib.suppress(Exception):
                await connection.disconnect()

    @property
    def is_connected(self) -> bool:
        """Há peer conectado e data channel validado."""
        connection = self._connection
        if connection is None:
            return False
        return bool(connection.isConnected and connection.datachannel.data_channel_opened)

    @property
    def pub_sub(self) -> PubSub:
        """Canal pub/sub da conexão atual, sem checar se o canal está aberto.

        Usado para assinar tópicos logo após conectar.

        Raises:
            RobotUnavailableError: se nunca houve conexão.
        """
        if self._connection is None:
            raise RobotUnavailableError(NOT_CONNECTED_MESSAGE)
        return self._connection.datachannel.pub_sub

    def ensure_connected(self) -> PubSub:
        """Devolve o canal pub/sub, exigindo conexão viva.

        Raises:
            RobotUnavailableError: se não há conexão viva com o robô.
        """
        if not self.is_connected:
            raise RobotUnavailableError(NOT_CONNECTED_MESSAGE)
        return self.pub_sub
