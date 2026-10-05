"""Dublês da conexão WebRTC.

Nada aqui abre rede: os testes exercitam o formato dos comandos despachados e
o comportamento HTTP da API; a validação contra o robô físico é manual.
"""

import asyncio
import json
from typing import Any

from app.robot.ports import StateCallback


class FakePubSub:
    """Registra o que teria sido enviado pelo canal de dados."""

    def __init__(self) -> None:
        """Começa sem nada enviado, assinado ou respondido."""
        self.sent: list[dict[str, Any]] = []
        self.subscriptions: dict[str, StateCallback] = {}
        self.response: dict[str, Any] | None = None
        self.hang_on_request = False

    def subscribe(self, topic: str, callback: StateCallback) -> None:
        """Guarda o callback para o teste poder simular mensagens."""
        self.subscriptions[topic] = callback

    def publish_without_callback(
        self, topic: str, data: Any = None, msg_type: str | None = None
    ) -> None:
        """Registra um envio sem resposta."""
        self.sent.append({"topic": topic, "data": data, "type": msg_type})

    async def publish_request_new(
        self, topic: str, options: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Registra uma request e devolve `response` (ou nunca responde)."""
        self.sent.append({"topic": topic, "options": options, "type": "req"})
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


class FakeConnection:
    """Conexão WebRTC falsa."""

    def __init__(self, connect_error: Exception | None = None) -> None:
        """Cria a conexão, opcionalmente fadada a falhar ao conectar."""
        self.isConnected = False
        self.datachannel = FakeDataChannel()
        self.connect_error = connect_error
        self.disconnected = False

    async def connect(self) -> None:
        """Marca como conectada, ou falha se configurada para tal."""
        if self.connect_error is not None:
            raise self.connect_error
        self.isConnected = True

    async def disconnect(self) -> None:
        """Marca como desconectada."""
        self.disconnected = True
        self.isConnected = False


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
