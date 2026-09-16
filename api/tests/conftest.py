"""Fixtures dos testes.

Todos os testes rodam com o robô inacessível — nada aqui abre WebRTC. O que é
exercitado é o formato dos comandos despachados e o comportamento HTTP da API;
a validação contra o robô físico é manual e acontece depois.
"""

from __future__ import annotations

import json
import os
from typing import Any

import pytest

# Definido antes de qualquer import de `app.main`, que instancia a app no nível
# do módulo e por isso exige configuração válida já na importação.
os.environ.setdefault("GO2_ROBOT_IP", "192.168.1.50")
os.environ.setdefault("GO2_CONNECT_ON_STARTUP", "false")

from app.config import ConnectionMethod, Settings
from app.robot import RobotConnection


@pytest.fixture
def settings() -> Settings:
    return Settings(
        connection_method=ConnectionMethod.local_sta,
        robot_ip="192.168.1.50",
        connect_on_startup=False,
        move_rate_hz=50.0,
        move_max_duration_s=10.0,
        max_vx=1.0,
        max_vy=1.0,
        max_vyaw=2.0,
        request_timeout_s=0.2,
    )


class FakePubSub:
    """Registra o que teria sido enviado pelo canal de dados."""

    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []
        self.subscriptions: dict[str, Any] = {}
        self.response: Any = None

    def publish_without_callback(self, topic, data=None, msg_type=None) -> None:
        self.sent.append({"topic": topic, "data": data, "type": msg_type})

    async def publish_request_new(self, topic, options=None):
        self.sent.append({"topic": topic, "options": options, "type": "req"})
        if self.response is None:
            raise AssertionError("Nenhuma resposta configurada no FakePubSub.")
        return self.response

    def subscribe(self, topic, callback=None) -> None:
        self.subscriptions[topic] = callback

    # ─── Helpers de teste ──────────────────────────────────────────────────

    @property
    def api_ids(self) -> list[int]:
        return [
            msg["data"]["header"]["identity"]["api_id"]
            for msg in self.sent
            if "data" in msg
        ]

    def parameter_of(self, index: int) -> Any:
        raw = self.sent[index]["data"]["parameter"]
        return json.loads(raw) if raw != "" else None


class FakeDataChannel:
    def __init__(self) -> None:
        self.data_channel_opened = True
        self.pub_sub = FakePubSub()


class FakeConnection:
    def __init__(self) -> None:
        self.isConnected = True
        self.datachannel = FakeDataChannel()
        self.disconnected = False

    async def disconnect(self) -> None:
        self.disconnected = True
        self.isConnected = False


@pytest.fixture
def fake_conn() -> FakeConnection:
    return FakeConnection()


@pytest.fixture
def robot(settings: Settings, fake_conn: FakeConnection) -> RobotConnection:
    """`RobotConnection` com uma conexão falsa já "aberta" e assinada."""
    conn = RobotConnection(settings)
    conn._conn = fake_conn
    conn._subscribe_state()
    return conn


@pytest.fixture
def offline_robot(settings: Settings) -> RobotConnection:
    """`RobotConnection` sem conexão nenhuma — o robô desligado."""
    return RobotConnection(settings)


@pytest.fixture
def pub_sub(fake_conn: FakeConnection) -> FakePubSub:
    return fake_conn.datachannel.pub_sub
