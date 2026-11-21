"""Dublês da conexão WebRTC.

Nada aqui abre rede: os testes exercitam o formato dos comandos despachados e
o comportamento HTTP da API; a validação contra o robô físico é manual.
"""

import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import Any

from app.robot.ports import StateCallback

# Calcula a resposta de uma request a partir das `options` dela.
Responder = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


class FakePubSub:
    """Registra o que teria sido enviado pelo canal de dados."""

    def __init__(self) -> None:
        """Começa sem nada enviado, assinado ou respondido."""
        self.sent: list[dict[str, Any]] = []
        self.subscriptions: dict[str, StateCallback] = {}
        self.response: dict[str, Any] | None = None
        self.hang_on_request = False
        # Se definido, responde cada request pelas `options` (vence `response`).
        self.responder: Responder | None = None
        self.subscribe_calls: list[str] = []
        self.unsubscribed: list[str] = []

    def subscribe(self, topic: str, callback: StateCallback) -> None:
        """Guarda o callback para o teste poder simular mensagens."""
        self.subscribe_calls.append(topic)
        self.subscriptions[topic] = callback

    def unsubscribe(self, topic: str) -> None:
        """Registra o cancelamento; como a lib, não remove o callback."""
        self.unsubscribed.append(topic)

    def publish_without_callback(
        self, topic: str, data: Any = None, msg_type: str | None = None
    ) -> None:
        """Registra um envio sem resposta."""
        self.sent.append({"topic": topic, "data": data, "type": msg_type})

    async def publish_request_new(
        self, topic: str, options: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Registra uma request e devolve `response` (ou nunca responde).

        Com `responder`, cada request recebe a resposta calculada para ela,
        como a lib, que casa a resposta pelo id da request.
        """
        self.sent.append({"topic": topic, "options": options, "type": "req"})
        if self.responder is not None:
            return await self.responder(options or {})
        if self.hang_on_request:
            await asyncio.Event().wait()
        if self.response is None:
            msg = "Nenhuma resposta configurada no FakePubSub."
            raise AssertionError(msg)
        return self.response

    def publish_state(self, topic: str, data: dict[str, Any]) -> None:
        """Simula o robô publicando `data` em `topic`."""
        self.subscriptions[topic]({"type": "msg", "topic": topic, "data": data})

    @property
    def fire_and_forget(self) -> list[dict[str, Any]]:
        """Envios feitos por `publish_without_callback`."""
        return [msg for msg in self.sent if "data" in msg]

    @property
    def api_ids(self) -> list[int]:
        """`api_id` de cada comando enviado sem resposta, em ordem."""
        return [
            msg["data"]["header"]["identity"]["api_id"] for msg in self.fire_and_forget
        ]

    def parameter_of(self, index: int) -> Any:
        """Parâmetro (já decodificado) do `index`-ésimo comando enviado."""
        raw = self.fire_and_forget[index]["data"]["parameter"]
        return json.loads(raw) if raw != "" else None


class FakeDataChannel:
    """Data channel falso, aberto por padrão."""

    def __init__(self) -> None:
        """Cria o canal com um `FakePubSub`."""
        self.data_channel_opened = True
        self.pub_sub = FakePubSub()
        self.decoder: Any = None
        self.traffic_saving_calls: list[bool] = []
        # `True`/`False`: resposta; exceção: lançada; "hang": nunca responde.
        self.traffic_saving_result: bool | Exception | str = True
        self.switch_video_calls: list[bool] = []
        self.switch_video_error: Exception | None = None

    def switchVideoChannel(self, switch: bool) -> None:  # noqa: N802
        """Imita a lib: registra o pedido, sem resposta (ou lança o erro)."""
        self.switch_video_calls.append(switch)
        if self.switch_video_error is not None:
            raise self.switch_video_error

    async def disableTrafficSaving(self, switch: bool) -> bool:  # noqa: N802
        """Imita a lib: registra o pedido e devolve o resultado configurado."""
        self.traffic_saving_calls.append(switch)
        result = self.traffic_saving_result
        if result == "hang":
            await asyncio.Event().wait()
        if isinstance(result, Exception):
            raise result
        return bool(result)


class FakePeerConnection:
    """Imita o `on`/`emit` do `RTCPeerConnection` (pyee) sem abrir nada."""

    def __init__(self) -> None:
        """Começa em `new`, sem ouvintes."""
        self.connectionState = "new"
        self.handlers: dict[str, list[Callable[[], object]]] = {}

    def on(self, event: str, handler: Callable[[], object], /) -> object:
        """Acrescenta `handler` aos ouvintes de `event`, como o pyee."""
        self.handlers.setdefault(event, []).append(handler)
        return handler

    def emit_state(self, state: str) -> None:
        """Muda `connectionState` e dispara `connectionstatechange`."""
        self.connectionState = state
        for handler in self.handlers.get("connectionstatechange", []):
            handler()


class FakeConnection:
    """Conexão WebRTC falsa."""

    def __init__(self, connect_error: Exception | None = None) -> None:
        """Cria a conexão, opcionalmente fadada a falhar ao conectar."""
        self.isConnected = False
        self.datachannel = FakeDataChannel()
        self.pc = FakePeerConnection()
        self.connect_error = connect_error
        self.disconnected = False
        self.video_track_listener: Callable[[Any], None] | None = None
        # Track entregue ao ouvinte durante o `connect()`, como a lib 2.2.0.
        self.video_track: Any = None

    async def connect(self) -> None:
        """Marca como conectada, ou falha se configurada para tal."""
        if self.connect_error is not None:
            raise self.connect_error
        if self.video_track is not None and self.video_track_listener is not None:
            self.video_track_listener(self.video_track)
        self.isConnected = True
        self.pc.connectionState = "connected"

    async def disconnect(self) -> None:
        """Marca como desconectada; o peer emite `closed`, como no aiortc."""
        self.disconnected = True
        self.isConnected = False
        self.pc.emit_state("closed")


class FakeConnectionFactory:
    """Fábrica que sempre entrega a mesma `FakeConnection`."""

    def __init__(self, connection: FakeConnection | None = None) -> None:
        """Guarda a conexão a entregar."""
        self.connection = connection or FakeConnection()
        self.calls = 0

    def __call__(self) -> FakeConnection:
        """Devolve a conexão e conta a chamada."""
        self.calls += 1
        return self.connection

    @property
    def pub_sub(self) -> FakePubSub:
        """Atalho para o `FakePubSub` da conexão."""
        return self.connection.datachannel.pub_sub


class TrackEndedError(Exception):
    """Fim da track, como o `MediaStreamError` do aiortc."""


class FakeVideoTrack:
    """Track de vídeo falsa: entrega os quadros que o teste põe na fila."""

    def __init__(self) -> None:
        """Começa vazia; a fila não tem limite, como a do aiortc."""
        self._queue: asyncio.Queue[Any] = asyncio.Queue()
        self.received = 0

    def put(self, frame: Any) -> None:
        """Simula o aiortc entregando um quadro decodificado."""
        self._queue.put_nowait(frame)

    def end(self) -> None:
        """Simula o fim da track."""
        self._queue.put_nowait(TrackEndedError())

    def pending(self) -> int:
        """Quadros que ninguém leu ainda."""
        return self._queue.qsize()

    async def recv(self) -> Any:
        """Devolve o próximo quadro; com a track encerrada, lança erro."""
        item = await self._queue.get()
        if isinstance(item, Exception):
            raise item
        self.received += 1
        return item
