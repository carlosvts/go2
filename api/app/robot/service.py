"""Fachada da camada do robô, usada pela API."""

import asyncio
import logging
import time
from typing import Any, Self

from app.config import Settings
from app.robot.audio import AudioHub
from app.robot.channel import (
    AudioHubChannel,
    ObstacleAvoidChannel,
    SportChannel,
    VuiChannel,
)
from app.robot.commands import MoveCommand, SportCommand
from app.robot.connection import (
    ConnectionListener,
    ConnectionSnapshot,
    ConnectionState,
)
from app.robot.device import DeviceControls
from app.robot.errors import ActiveErrors
from app.robot.lidar import LidarStream
from app.robot.link import RobotLink
from app.robot.movement import MoveController
from app.robot.ports import ConnectionFactory
from app.robot.safety import ObstacleAvoidanceReading
from app.robot.speaker import Speaker
from app.robot.speed import SpeedReading
from app.robot.state import RobotStatus, StateCache
from app.robot.state_stream import StateStream
from app.robot.streams import TrafficSaving
from app.robot.unitree import UnitreeConnectionFactory
from app.robot.video import VideoStream

log = logging.getLogger(__name__)

SPEAKER_TOPIC = "speaker"
"""Tópico do alto-falante (F-007) no `/ws/state`."""
AUDIO_PLAYER_TOPIC = "audio_player"
"""Tópico do player do robô (F-006) no `/ws/state`."""


class Go2Robot:
    """Dona única da conexão WebRTC com o Go2 (padrão *Facade*).

    Esconde os colaboradores — conexão, canal de envio, cache de estado e
    controlador de movimento — atrás de uma interface de comandos. Os
    consumidores HTTP não precisam saber nada de WebRTC.
    """

    def __init__(  # noqa: PLR0913 - colaboradores injetados, todos por nome
        self,
        *,
        link: RobotLink,
        channel: SportChannel,
        obstacle_avoid: ObstacleAvoidChannel,
        state: StateCache,
        movement: MoveController,
        lidar: LidarStream,
        video: VideoStream,
        device: DeviceControls,
        errors: ActiveErrors,
        state_stream: StateStream,
        speaker: Speaker,
        audio: AudioHub,
    ) -> None:
        """Recebe os colaboradores já montados (ver :meth:`from_settings`)."""
        self._link = link
        self._channel = channel
        self._obstacle_avoid = obstacle_avoid
        self._state = state
        self._movement = movement
        self._lidar = lidar
        self._video = video
        self._device = device
        self._errors = errors
        self._state_stream = state_stream
        self._speaker = speaker
        self._audio = audio
        self._wire_audio()

    def _wire_audio(self) -> None:
        """Liga o áudio (F-006, F-007) ao `/ws/state` (F-004) e ao `silence`.

        - `speaker`: mudança de estado pelo caminho sem descarte; no aceite, o
          estado atual.
        - `audio_player`: o `data` cru do player do robô, pelo caminho das
          seções (com o teto `GO2_STATE_MAX_HZ`); no aceite, o último valor.
        - `POST /audio/silence` também para o alto-falante.
        """
        speaker, stream, audio = self._speaker, self._state_stream, self._audio
        speaker.subscribe(
            lambda snapshot: stream.publish_event(SPEAKER_TOPIC, snapshot)
        )
        audio.subscribe_player_state(
            lambda data: stream.publish_section(AUDIO_PLAYER_TOPIC, data)
        )

        def snapshot() -> list[tuple[str, float, Any]]:
            now = time.time()
            current = [(SPEAKER_TOPIC, now, speaker.snapshot.as_dict())]
            player = audio.player()
            if player.data is not None and player.age_s is not None:
                current.insert(0, (AUDIO_PLAYER_TOPIC, now - player.age_s, player.data))
            return current

        stream.add_snapshot_provider(snapshot)

        async def stop_speaker() -> None:
            await speaker.stop()

        audio.set_speaker_stopper(stop_speaker)

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
        # O vídeo usa o mesmo data channel do LiDAR (F-003).
        traffic = TrafficSaving(settings.request_timeout_s)
        # Erros do data channel (F-004): só os da conexão atual; `None` na queda.
        errors = ActiveErrors()
        link.subscribe_datachannel_messages(errors.on_message)
        link.state.subscribe(errors.on_connection)
        state = StateCache()
        return cls(
            link=link,
            channel=channel,
            obstacle_avoid=ObstacleAvoidChannel(link, settings.request_timeout_s),
            state=state,
            movement=MoveController(channel, settings.move_rate_hz),
            lidar=LidarStream(
                link,
                max_clients=settings.lidar_max_clients,
                client_queue=settings.lidar_client_queue,
                decode_queue=settings.lidar_decode_queue,
                request_timeout_s=settings.request_timeout_s,
                telemetry_max_clients=settings.telemetry_max_clients,
                telemetry_queue=settings.telemetry_client_queue,
                traffic=traffic,
            ),
            video=VideoStream(
                link,
                traffic=traffic,
                max_clients=settings.video_max_clients,
                client_queue=settings.video_client_queue,
                encode_queue=settings.video_encode_queue,
                max_fps=settings.video_max_fps,
                jpeg_quality=settings.video_jpeg_quality,
                stall_s=settings.video_stall_s,
            ),
            device=DeviceControls(VuiChannel(link, settings.request_timeout_s)),
            errors=errors,
            state_stream=StateStream(
                link,
                state,
                errors,
                max_clients=settings.state_max_clients,
                max_hz=settings.state_max_hz,
            ),
            speaker=Speaker(link),
            audio=AudioHub(
                AudioHubChannel(link, settings.request_timeout_s),
                link,
                max_upload_bytes=settings.audio_max_upload_bytes,
            ),
        )

    # ─── Ciclo de vida ─────────────────────────────────────────────────────

    async def connect(self) -> None:
        """Abre a conexão e assina os tópicos de estado.

        Se a abertura falha, erros que a tentativa tenha mandado durante o
        `connect()` são esquecidos: a lista volta a `None` (desconhecido).
        """
        try:
            await self._link.connect()
        except BaseException:
            self._errors.reset(notify=True)
            raise
        self._state.attach(self._link.pub_sub)
        self._audio.attach(self._link.pub_sub)
        # Emoji para localizar a linha rápido no terminal.
        log.info("🐝 Conectado ao Go2.")

    async def disconnect(self) -> None:
        """Cancela o movimento e o envio de áudio em curso e encerra a conexão."""
        await self._movement.cancel()
        await self._audio.cancel_upload()
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

    @property
    def lidar(self) -> LidarStream:
        """Stream de nuvem de pontos do LiDAR (`/ws/lidar`)."""
        return self._lidar

    @property
    def video(self) -> VideoStream:
        """Stream de vídeo da câmera frontal (`/ws/video`)."""
        return self._video

    @property
    def device(self) -> DeviceControls:
        """Lanterna, LED e volume (`/device/*`, F-005)."""
        return self._device

    @property
    def state_stream(self) -> StateStream:
        """Stream do estado e dos erros ativos (`/ws/state`, F-004)."""
        return self._state_stream

    @property
    def speaker(self) -> Speaker:
        """Alto-falante pela track de áudio WebRTC (`/speaker/*`, F-007)."""
        return self._speaker

    @property
    def audio(self) -> AudioHub:
        """Biblioteca de áudio do robô (`/audio/*`, F-006)."""
        return self._audio

    # ─── Estado ────────────────────────────────────────────────────────────

    def status(self) -> RobotStatus:
        """Snapshot do cache de estado; nunca fala com o robô."""
        return self._state.snapshot(
            connected=self.is_connected,
            connection=self.connection,
            errors=self._errors.current,
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

    # ─── Segurança ─────────────────────────────────────────────────────────

    async def set_obstacle_avoidance(self, *, enabled: bool) -> None:
        """Liga ou desliga o desvio de obstáculo nativo, sem esperar resposta.

        A API diz `enabled`; o robô espera `enable`. Pendente de validação
        física: se o desvio ligado filtra o `Move` despachado por
        :meth:`start_move` (dossiê 12.1).
        """
        self._obstacle_avoid.send("SWITCH_SET", {"enable": enabled})

    async def get_obstacle_avoidance(self) -> ObstacleAvoidanceReading:
        """Consulta se o desvio está ligado, aguardando a resposta do robô."""
        return ObstacleAvoidanceReading.from_response(
            await self._obstacle_avoid.request("SWITCH_GET")
        )
