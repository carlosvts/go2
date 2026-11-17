"""Rota `/ws/telemetry` com a app real e o robô falso (F-002)."""

import json
import time
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.config import Settings
from app.main import create_app
from app.robot.unitree import RTC_TOPIC
from tests.fakes import FakeConnectionFactory, FakePubSub

POSE = RTC_TOPIC["ROBOTODOM"]


def _wait_subscribed(pub_sub: FakePubSub, topic: str, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while topic not in pub_sub.subscriptions:
        assert time.monotonic() < deadline, f"{topic} não foi assinado"
        time.sleep(0.01)


@pytest.fixture
def zero_telemetry(
    factory: FakeConnectionFactory, settings: Settings
) -> Iterator[TestClient]:
    app = create_app(
        settings.model_copy(update={"telemetry_max_clients": 0}),
        connection_factory=factory,
    )
    with TestClient(app) as test_client:
        yield test_client


def test_a1_conexao_primeiro_e_metricas_em_seguida(client: TestClient) -> None:
    with client.websocket_connect("/ws/telemetry") as ws:
        first = json.loads(ws.receive_text())
        # A janela padrão é de 1 s; a ativação não manda nada de texto.
        second = json.loads(ws.receive_text())

    assert first["topic"] == "connection"
    assert first["data"] == {"state": "connected"}
    assert second["topic"] == "lidar_metrics"
    assert second["data"]["clients"] == {"lidar": 0, "telemetry": 1}
    assert second["data"]["dropped"] == 0


def test_a1_robo_fora_do_ar(offline_client: TestClient) -> None:
    with offline_client.websocket_connect("/ws/telemetry") as ws:
        assert json.loads(ws.receive_text())["data"]["state"] == "disconnected"
        metrics = json.loads(ws.receive_text())

    assert metrics["data"]["active"] is False


def test_pose_do_robo_chega_como_lidar_pose(
    client: TestClient, pub_sub: FakePubSub
) -> None:
    with client.websocket_connect("/ws/telemetry") as ws:
        ws.receive_text()
        _wait_subscribed(pub_sub, POSE)
        assert client.portal is not None
        client.portal.call(pub_sub.publish_state, POSE, {"x": 1.5, "raw": b"\x01"})

        frame = json.loads(ws.receive_text())

    assert frame["topic"] == "lidar_pose"
    assert frame["data"] == {"x": 1.5, "raw": {"base64": "AQ=="}}


def test_a14_segundo_cliente_leva_1013_e_lidar_segue_livre(client: TestClient) -> None:
    with client.websocket_connect("/ws/telemetry") as first:
        first.receive_text()
        with (
            client.websocket_connect("/ws/telemetry") as second,
            pytest.raises(WebSocketDisconnect) as closed,
        ):
            second.receive_text()
        with client.websocket_connect("/ws/lidar") as lidar:
            assert json.loads(lidar.receive_text())["topic"] == "connection"

    assert closed.value.code == 1013


def test_a14_limite_zero_desliga_a_rota(zero_telemetry: TestClient) -> None:
    with (
        zero_telemetry.websocket_connect("/ws/telemetry") as ws,
        pytest.raises(WebSocketDisconnect) as closed,
    ):
        ws.receive_text()

    assert closed.value.code == 1013
