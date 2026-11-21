"""Rota `/ws/lidar` com a app real e o robô falso (F-001)."""

import json
import time
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.config import Settings
from app.main import create_app
from app.robot.lidar import FRAME_HEADER
from tests.fakes import FakeConnectionFactory, FakePubSub
from tests.lidar_payloads import LIDAR_TOPIC, lidar_message, voxel_bitmap


def _wait_subscribed(pub_sub: FakePubSub, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while LIDAR_TOPIC not in pub_sub.subscriptions:
        assert time.monotonic() < deadline, "LiDAR não foi assinado"
        time.sleep(0.01)


def _wait_unsubscribed(pub_sub: FakePubSub, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while LIDAR_TOPIC in pub_sub.subscriptions:
        assert time.monotonic() < deadline, "LiDAR continuou assinado"
        time.sleep(0.01)


@pytest.fixture
def zero_clients(
    factory: FakeConnectionFactory, settings: Settings
) -> Iterator[TestClient]:
    app = create_app(
        settings.model_copy(update={"lidar_max_clients": 0}),
        connection_factory=factory,
    )
    with TestClient(app) as test_client:
        yield test_client


def test_primeiro_frame_e_o_estado_da_conexao(client: TestClient) -> None:
    with client.websocket_connect("/ws/lidar") as ws:
        message = json.loads(ws.receive_text())

    assert message["topic"] == "connection"
    assert message["data"] == {"state": "connected"}
    assert isinstance(message["ts"], float)


def test_robo_fora_do_ar_mantem_o_cliente_esperando(offline_client: TestClient) -> None:
    with offline_client.websocket_connect("/ws/lidar") as ws:
        assert json.loads(ws.receive_text())["data"]["state"] == "disconnected"


def test_mensagem_do_robo_vira_frame_binario(
    client: TestClient, pub_sub: FakePubSub
) -> None:
    with client.websocket_connect("/ws/lidar") as ws:
        ws.receive_text()
        _wait_subscribed(pub_sub)
        assert client.portal is not None
        client.portal.call(
            pub_sub.subscriptions[LIDAR_TOPIC], lidar_message(voxel_bitmap())
        )

        frame = ws.receive_bytes()

    version, _, header_len, seq, *_ = FRAME_HEADER.unpack_from(frame, 0)
    assert (version, header_len, seq) == (1, 40, 0)


def test_a11_segundo_cliente_leva_1013_com_o_limite_padrao(client: TestClient) -> None:
    with client.websocket_connect("/ws/lidar") as first:
        first.receive_text()
        with (
            client.websocket_connect("/ws/lidar") as second,
            pytest.raises(WebSocketDisconnect) as closed,
        ):
            second.receive_text()

    assert closed.value.code == 1013


def test_a11_limite_zero_desliga_a_rota(zero_clients: TestClient) -> None:
    with (
        zero_clients.websocket_connect("/ws/lidar") as ws,
        pytest.raises(WebSocketDisconnect) as closed,
    ):
        ws.receive_text()

    assert closed.value.code == 1013


def test_cliente_que_sai_libera_a_vaga_e_desativa(
    client: TestClient, pub_sub: FakePubSub, factory: FakeConnectionFactory
) -> None:
    with client.websocket_connect("/ws/lidar") as ws:
        ws.receive_text()
        _wait_subscribed(pub_sub)

    _wait_unsubscribed(pub_sub)
    assert factory.connection.datachannel.traffic_saving_calls == [True, False]
    with client.websocket_connect("/ws/lidar") as ws:
        assert json.loads(ws.receive_text())["topic"] == "connection"


def test_a11_status_segue_respondendo_com_lidar_ativo(
    client: TestClient, pub_sub: FakePubSub
) -> None:
    with client.websocket_connect("/ws/lidar") as ws:
        ws.receive_text()
        _wait_subscribed(pub_sub)

        response = client.get("/status")

    assert response.status_code == 200
    assert response.json()["connected"] is True
