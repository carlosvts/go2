"""Ciclo de vida da conexão WebRTC com o robô."""

import contextlib
import functools
import logging
from typing import Any

from app.exceptions import RobotUnavailableError
from app.robot.connection import ConnectionState, ConnectionStateTracker
from app.robot.ports import (
    AudioTrack,
    ConnectionFactory,
    DataChannel,
    DataChannelMessageListener,
    PeerConnection,
    PubSub,
    VideoTrack,
    VideoTrackListener,
    WebRTCConnection,
)

log = logging.getLogger(__name__)

NOT_CONNECTED_MESSAGE = "❌ Sem conexão com o robô."


class RobotLink:
    """Dona da conexão: abre, fecha e informa se ela está viva.

    O WebRTC é ponto-a-ponto — só existe uma conexão por vez com o robô —, então
    esta classe é instanciada uma única vez por processo. Ela não reconecta
    sozinha: quem decide tentar de novo é
    :meth:`~app.robot.service.Go2Robot.keep_connected`.
    """

    def __init__(
        self,
        factory: ConnectionFactory,
        state: ConnectionStateTracker | None = None,
    ) -> None:
        """Recebe a fábrica de conexões e, opcionalmente, o rastreador de estado."""
        self._factory = factory
        self._state = state or ConnectionStateTracker()
        self._connection: WebRTCConnection | None = None
        self._connecting: WebRTCConnection | None = None
        self._track_listeners: list[VideoTrackListener] = []
        self._datachannel_listeners: list[DataChannelMessageListener] = []

    def subscribe_video_track(self, listener: VideoTrackListener) -> None:
        """Registra `listener` para receber a track de vídeo de cada conexão.

        A lib entrega a track durante o `connect()`, antes de ele retornar
        (F-003): o ouvinte precisa estar registrado antes de conectar.
        """
        self._track_listeners.append(listener)

    def _emit_video_track(self, track: VideoTrack) -> None:
        for listener in self._track_listeners:
            try:
                listener(track)
            except Exception:
                log.exception("❌ Falha num ouvinte da track de vídeo.")

    def subscribe_datachannel_messages(
        self, listener: DataChannelMessageListener
    ) -> None:
        """Registra `listener` para as mensagens de erro do data channel (F-004).

        Só chegam as da conexão atual ou da que está abrindo (inclusive durante
        o `connect()`); as de uma conexão antiga são descartadas.
        """
        self._datachannel_listeners.append(listener)

    def _emit_datachannel_message(
        self, connection: WebRTCConnection, channel: object, message: dict[str, Any]
    ) -> None:
        if connection is not self._connection and connection is not self._connecting:
            return
        for listener in self._datachannel_listeners:
            try:
                listener(channel, message)
            except Exception:
                log.exception("❌ Falha num ouvinte do data channel.")

    async def connect(self) -> None:
        """Cria e abre a conexão; só a guarda se a abertura der certo.

        Se a abertura falha, o estado publicado não muda e a conexão que
        ficou pela metade é fechada — sem isso cada tentativa de reconexão
        deixaria um peer aberto para trás.
        """
        connection = self._factory()
        connection.video_track_listener = self._emit_video_track
        connection.datachannel_message_listener = functools.partial(
            self._emit_datachannel_message, connection
        )
        self._connecting = connection
        try:
            await connection.connect()
        except BaseException:
            # BaseException: inclui o cancelamento da tarefa no meio da abertura.
            with contextlib.suppress(Exception):
                await connection.disconnect()
            raise
        finally:
            self._connecting = None
        self._connection = connection
        peer = connection.pc
        # O pyee aceita vários ouvintes por evento: o da lib, que atualiza
        # `isConnected`, continua registrado. Ela não expõe evento de queda
        # próprio, então este ouvinte acopla o código ao aiortc.
        peer.on(
            "connectionstatechange",
            lambda: self._on_peer_state_change(connection, peer),
        )
        self._state.update(ConnectionState.connected, reason=peer.connectionState)

    async def disconnect(self) -> None:
        """Encerra a conexão, ignorando falhas de encerramento."""
        connection, self._connection = self._connection, None
        if connection is not None:
            with contextlib.suppress(Exception):
                await connection.disconnect()
            self._state.update(ConnectionState.disconnected, reason="closed")

    def _on_peer_state_change(
        self, connection: WebRTCConnection, peer: PeerConnection
    ) -> None:
        """Repassa o `connectionState` do peer ao rastreador.

        Eventos de uma conexão que já não é a atual (o `closed` emitido
        durante o próprio :meth:`disconnect`, por exemplo) são ignorados.
        """
        if connection is self._connection:
            self._state.on_peer_state(peer.connectionState)

    @property
    def state(self) -> ConnectionStateTracker:
        """Estado publicado da conexão — informativo, não decide os `503`."""
        return self._state

    @property
    def is_connected(self) -> bool:
        """Há peer conectado e data channel validado.

        É a fonte da verdade para aceitar comandos ou responder `503`.
        """
        connection = self._connection
        if connection is None:
            return False
        return bool(
            connection.isConnected and connection.datachannel.data_channel_opened
        )

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

    @property
    def datachannel(self) -> DataChannel | None:
        """Data channel da conexão atual, ou `None` se nunca houve conexão.

        Muda a cada conexão: compare por identidade para saber se ainda é o
        mesmo canal.
        """
        if self._connection is None:
            return None
        return self._connection.datachannel

    @property
    def connection_key(self) -> object | None:
        """Identidade opaca da conexão atual (`None` sem conexão).

        Muda a cada `connect()`: compare por identidade (`is`) para saber se
        algo instalado numa conexão ainda vale (F-007).
        """
        return self._connection

    def attach_audio_track(self, track: AudioTrack) -> object:
        """Põe `track` no transceiver de áudio da conexão viva.

        Returns:
            A :attr:`connection_key` da conexão em que a track ficou.

        Raises:
            RobotUnavailableError: se não há conexão viva com o robô.
        """
        connection = self._connection
        if connection is None or not self.is_connected:
            raise RobotUnavailableError(NOT_CONNECTED_MESSAGE)
        connection.attach_audio_track(track)
        return connection

    def ensure_connected(self) -> PubSub:
        """Devolve o canal pub/sub, exigindo conexão viva.

        Raises:
            RobotUnavailableError: se não há conexão viva com o robô.
        """
        if not self.is_connected:
            raise RobotUnavailableError(NOT_CONNECTED_MESSAGE)
        return self.pub_sub
