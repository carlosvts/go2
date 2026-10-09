"""Fachada da camada do robô, usada pela API."""

import asyncio
import logging
from typing import Any, Self

from app.config import Settings
from app.robot.channel import SportChannel
from app.robot.commands import MoveCommand, SportCommand
from app.robot.connection import (
    ConnectionListener,
    ConnectionSnapshot,
    ConnectionState,
)
from app.robot.link import RobotLink
from app.robot.movement import MoveController
from app.robot.ports import ConnectionFactory
from app.robot.speed import SpeedReading
from app.robot.state import RobotStatus, StateCache
from app.robot.unitree import UnitreeConnectionFactory

log = logging.getLogger(__name__)


class Go2Robot:
    """Dona única da conexão WebRTC com o Go2 (padrão *Facade*).

    Esconde os colaboradores — conexão, canal de envio, cache de estado e
    controlador de movimento — atrás de uma interface de comandos. Os
    consumidores HTTP não precisam saber nada de WebRTC.
    """

    def __init__(
        self,
        *,
        link: RobotLink,
        channel: SportChannel,
        state: StateCache,
        movement: MoveController,
    ) -> None:
        """Recebe os colaboradores já montados (ver :meth:`from_settings`)."""
        self._link = link
        self._channel = channel
        self._state = state
        self._movement = movement

    @classmethod
    def from_settings(
        cls,
        settings: Settings,
        connection_factory: ConnectionFactory | None = None,
    ) -> Self:
        """Monta o grafo de objetos a partir da configuração.

        Args:
            settings: Configuração da API.
            connection_factory: Fábrica de conexões. O padrão cria a conexão
                real com a lib da Unitree; testes injetam uma falsa.
        """
        factory = connection_factory or UnitreeConnectionFactory(settings)
        link = RobotLink(factory)
        channel = SportChannel(link, settings.request_timeout_s)
        return cls(
            link=link,
            channel=channel,
            state=StateCache(),
            movement=MoveController(channel, settings.move_rate_hz),
        )

    # ─── Ciclo de vida ─────────────────────────────────────────────────────

    async def connect(self) -> None:
        """Abre a conexão e assina os tópicos de estado."""
        await self._link.connect()
        self._state.attach(self._link.pub_sub)
        # Emoji para localizar a linha rápido no terminal.
        log.info("🐝 Conectado ao Go2.")

    async def disconnect(self) -> None:
        """Cancela o movimento em curso e encerra a conexão."""
        await self._movement.cancel()
        await self._link.disconnect()

    async def keep_connected(self, interval_s: float) -> None:
        """Mantém a conexão viva: roda para sempre, em segundo plano.

        A cada `interval_s` confere a conexão e, se ela caiu, tenta abrir uma
        nova. Nenhum comando é guardado nem reenviado: até a conexão voltar
        eles levam `503`, e o robô volta parado.

        Limitação: a descoberta e a sinalização da lib são síncronas, então
        cada tentativa trava o event loop por alguns segundos com o robô fora
        do ar.

        Args:
            interval_s: Segundos entre as verificações.
        """
        while True:
            await asyncio.sleep(interval_s)
            if not self._is_healthy:
                await self._reconnect()

    @property
    def _is_healthy(self) -> bool:
        """A conexão aceita comandos e o peer não avisou que caiu.

        O estado publicado entra na conta porque a lib mantém `isConnected`
        em `True` quando o peer vai para `failed`.
        """
        return self.is_connected and self.connection.state is ConnectionState.connected

    async def _reconnect(self) -> None:
        """Descarta a conexão antiga e tenta abrir uma nova.

        A fábrica cria uma conexão do zero a cada tentativa: com serial
        configurado, isso refaz a descoberta e acompanha uma troca de IP.
        """
        await self.disconnect()
        self._link.state.update(ConnectionState.reconnecting, reason="retry")
        try:
            await self.connect()
        except Exception as exc:
            log.warning("❌ Sem conexão com o robô (%s). Tentando de novo.", exc)

    @property
    def is_connected(self) -> bool:
        """Há conexão viva com o robô; decide se os comandos levam `503`."""
        return self._link.is_connected

    @property
    def connection(self) -> ConnectionSnapshot:
        """Estado publicado da conexão e o momento da última transição."""
        return self._link.state.current

    def subscribe_connection(self, listener: ConnectionListener) -> None:
        """Registra `listener` para receber `{"state", "reason"}` a cada transição."""
        self._link.state.subscribe(listener)

    # ─── Estado ────────────────────────────────────────────────────────────

    def status(self) -> RobotStatus:
        """Snapshot do cache de estado; nunca fala com o robô."""
        return self._state.snapshot(
            connected=self.is_connected, connection=self.connection
        )

    @property
    def raw_state(self) -> dict[str, dict[str, Any] | None]:
        """Payloads crus em cache."""
        return self._state.raw

    # ─── Comandos ──────────────────────────────────────────────────────────

    async def execute(self, command: SportCommand) -> None:
        """Executa uma postura ou gesto, cancelando qualquer movimento ativo.

        O robô não anda e gesticula ao mesmo tempo. Pendente de validação
        física: se o robô ignora um gesto pedido de barriga no chão, ou se
        `StopMove` interrompe um gesto em curso.
        """
        await self._movement.cancel()
        self._channel.send(command.sport_cmd)

    async def start_move(self, move: MoveCommand) -> None:
        """Inicia um movimento contínuo; substitui o que estiver em curso."""
        await self._movement.start(move)

    async def stop(self) -> None:
        """Parada imediata: cancela o reenvio e manda `StopMove`.

        Para desenergizar as juntas use a postura `damp`.
        """
        await self._movement.cancel()
        self._channel.send("StopMove")

    async def set_speed_level(self, level: int) -> None:
        """Define o nível de velocidade.

        Pendente de validação física: o envelope `{"data": <nível>}` do
        `SpeedLevel` (1015) não está documentado.
        """
        self._channel.send("SpeedLevel", {"data": level})

    async def get_speed_level(self) -> SpeedReading:
        """Consulta o nível de velocidade, aguardando a resposta do robô."""
        return SpeedReading.from_response(await self._channel.request("GetSpeedLevel"))
