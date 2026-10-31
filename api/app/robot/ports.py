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

    def subscribe(self, topic: str, callback: StateCallback) -> None:
        """Registra `callback` para as mensagens de `topic`."""

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

    async def connect(self) -> None:
        """Abre a conexão."""

    async def disconnect(self) -> None:
        """Encerra a conexão."""


class ConnectionFactory(Protocol):
    """Cria conexões (ainda não abertas) com o robô."""

    def __call__(self) -> WebRTCConnection:
        """Devolve uma nova conexão, pronta para `connect()`."""
