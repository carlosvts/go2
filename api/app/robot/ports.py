"""Contratos que a camada do robô exige da conexão WebRTC.

São `Protocol`s estruturais: a lib real os satisfaz por duck typing e os testes
usam dublês simples, sem herança nem monkeypatch. É a aplicação do princípio
da inversão de dependência — o domínio depende destas abstrações, não da lib.
"""

from collections.abc import Callable
from typing import Any, Protocol

StateCallback = Callable[[dict[str, Any]], None]
"""Callback de assinatura: recebe a mensagem inteira `{"type", "topic", "data"}`."""


class PubSub(Protocol):
    """Canal publish/subscribe do data channel."""

    subscriptions: dict[str, StateCallback]
    """Callback por tópico. A lib guarda um só; `unsubscribe` não o remove."""

    def subscribe(self, topic: str, callback: StateCallback) -> None:
        """Registra `callback` para as mensagens de `topic`."""

    def unsubscribe(self, topic: str) -> None:
        """Pede ao robô para parar de mandar `topic` (o callback fica)."""

    def publish_without_callback(
        self, topic: str, data: object = None, msg_type: str | None = None
    ) -> None:
        """Publica `data` em `topic` sem aguardar resposta."""

    async def publish_request_new(
        self, topic: str, options: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Publica uma request e aguarda a resposta do robô."""


class DataChannel(Protocol):
    """Data channel WebRTC aberto com o robô."""

    @property
    def data_channel_opened(self) -> bool:
        """Indica se o canal de dados foi validado."""

    @property
    def pub_sub(self) -> PubSub:
        """Canal publish/subscribe deste data channel."""

    decoder: Any
    """Decoder de LiDAR que a lib chama ao receber o voxel map."""

    async def disableTrafficSaving(self, switch: bool) -> bool:  # noqa: N802
        """Liga (`True`) ou desfaz o envio sem economia de tráfego; sem timeout."""

    def switchVideoChannel(self, switch: bool) -> None:  # noqa: N802
        """Liga ou desliga a câmera (`"on"`/`"off"` no data channel), sem resposta."""


class VideoFrame(Protocol):
    """Quadro decodificado pelo aiortc (`av.VideoFrame`)."""

    @property
    def width(self) -> int:
        """Largura em pixels."""

    @property
    def height(self) -> int:
        """Altura em pixels."""

    @property
    def time(self) -> float | None:
        """Tempo na track (relógio RTP do robô), ou `None`."""

    def to_ndarray(self, **kwargs: Any) -> Any:  # noqa: ANN401
        """Converte para array numpy (pesa na CPU: fora do event loop)."""


class VideoTrack(Protocol):
    """Track de vídeo recebida (`RemoteStreamTrack` do aiortc)."""

    async def recv(self) -> Any:  # noqa: ANN401
        """Espera o próximo quadro; lança erro quando a track termina."""


class AudioTrack(Protocol):
    """Track de áudio de saída (`MediaStreamTrack` do aiortc, kind `audio`)."""

    kind: str

    async def recv(self) -> Any:  # noqa: ANN401
        """Próximo quadro a enviar (`av.AudioFrame`)."""


VideoTrackListener = Callable[[VideoTrack], None]
"""Recebe a track de vídeo de uma conexão, durante o `connect()`."""


class PeerConnection(Protocol):
    """`RTCPeerConnection` do aiortc, um `EventEmitter` do pyee."""

    @property
    def connectionState(self) -> str:  # noqa: N802 - nome ditado pelo aiortc
        """`new`, `connecting`, `connected`, `disconnected`, `failed` ou `closed`."""

    def on(self, event: str, handler: Callable[[], object], /) -> object:
        """Acrescenta `handler` aos ouvintes de `event`, sem substituir os outros."""


class WebRTCConnection(Protocol):
    """Conexão WebRTC com o robô (subconjunto usado pela API)."""

    @property
    def isConnected(self) -> bool:  # noqa: N802 - nome ditado pela lib
        """Indica se o peer WebRTC está conectado."""

    @property
    def datachannel(self) -> DataChannel:
        """Data channel da conexão."""

    @property
    def pc(self) -> PeerConnection:
        """Peer WebRTC; só existe depois de `connect()`."""

    video_track_listener: VideoTrackListener | None
    """Chamado com a track de vídeo durante o `connect()` (F-003)."""

    def attach_audio_track(self, track: AudioTrack) -> None:
        """Põe `track` no transceiver de áudio da conexão, sem renegociar (F-007)."""

    async def connect(self) -> None:
        """Abre a conexão."""

    async def disconnect(self) -> None:
        """Encerra a conexão."""


class ConnectionFactory(Protocol):
    """Cria conexões (ainda não abertas) com o robô."""

    def __call__(self) -> WebRTCConnection:
        """Devolve uma nova conexão, pronta para `connect()`."""
