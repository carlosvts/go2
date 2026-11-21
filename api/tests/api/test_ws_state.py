"""Rota `/ws/state` com a app real e o robô falso (F-004 A4, A7, A8)."""

import json
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from starlette.testclient import WebSocketTestSession
from starlette.websockets import WebSocketDisconnect

from app.config import Settings
from app.main import create_app
from app.robot.unitree import RTC_TOPIC
from tests.fakes import FakeConnectionFactory, FakePubSub
from tests.state_payloads import low_state, sport_state


@pytest.fixture
def zero_clients(
    factory: FakeConnectionFactory, settings: Settings
) -> Iterator[TestClient]:
    app = create_app(
        settings.model_copy(update={"state_max_clients": 0}),
        connection_factory=factory,
    )
    with TestClient(app) as test_client:
        yield test_client


def _receive(ws: WebSocketTestSession, count: int) -> list[dict[str, Any]]:
    return [json.loads(ws.receive_text()) for _ in range(count)]


def _call(client: TestClient, function: Any, *args: Any) -> None:
    assert client.portal is not None
    client.portal.call(function, *args)


def test_a4_ordem_ao_aceitar_e_depois_da_queda(
    client: TestClient, factory: FakeConnectionFactory, pub_sub: FakePubSub
) -> None:
    _call(client, pub_sub.publish_state, RTC_TOPIC["LOW_STATE"], low_state())

    with client.websocket_connect("/ws/state") as ws:
        accepted = _receive(ws, 5)
        _call(client, factory.connection.pc.emit_state, "failed")
        dropped = _receive(ws, 2)
        _call(client, factory.connection.pc.emit_state, "connected")
        back = _receive(ws, 1)
        _call(
            client, pub_sub.publish_state, RTC_TOPIC["SPORT_MOD_STATE"], sport_state()
        )
        sections = _receive(ws, 2)

    assert [f["topic"] for f in accepted] == [
        "connection",
        "battery",
        "motors",
        "body_temperature_c",
        "errors",
    ]
    assert accepted[0]["data"] == {"state": "connected"}
    assert accepted[1]["data"]["percent"] == 87
    assert accepted[-1]["data"] is None
    assert [(f["topic"], f["data"]) for f in dropped] == [
        ("connection", {"state": "disconnected"}),
        ("errors", None),
    ]
    assert [(f["topic"], f["data"]) for f in back] == [
        ("connection", {"state": "connected"}),
    ]
    assert [f["topic"] for f in sections] == ["imu", "motion"]


def test_robo_fora_do_ar_mantem_o_cliente(offline_client: TestClient) -> None:
    with offline_client.websocket_connect("/ws/state") as ws:
        frames = _receive(ws, 2)

    assert [(f["topic"], f["data"]) for f in frames] == [
        ("connection", {"state": "disconnected"}),
        ("errors", None),
    ]


def test_a7_quinto_cliente_leva_1013_com_o_limite_padrao(client: TestClient) -> None:
    sockets = [client.websocket_connect("/ws/state") for _ in range(4)]
    opened = [ws.__enter__() for ws in sockets]
    try:
        for ws in opened:
            ws.receive_text()
        with (
            client.websocket_connect("/ws/state") as extra,
            pytest.raises(WebSocketDisconnect) as closed,
        ):
            extra.receive_text()
    finally:
        for ws in sockets:
            ws.__exit__(None, None, None)

    assert closed.value.code == 1013
    assert closed.value.reason == "max_clients"


def test_a7_limite_zero_desliga_a_rota(zero_clients: TestClient) -> None:
    with (
        zero_clients.websocket_connect("/ws/state") as ws,
        pytest.raises(WebSocketDisconnect) as closed,
    ):
        ws.receive_text()

    assert closed.value.code == 1013


def test_a8_clientes_nao_assinam_nem_cancelam_no_robo(
    client: TestClient, pub_sub: FakePubSub
) -> None:
    before = list(pub_sub.subscribe_calls)
    sent = list(pub_sub.sent)

    with client.websocket_connect("/ws/state") as ws:
        ws.receive_text()
    with client.websocket_connect("/ws/state") as ws:
        ws.receive_text()

    assert pub_sub.subscribe_calls == before
    assert RTC_TOPIC["MULTIPLE_STATE"] in before
    assert pub_sub.unsubscribed == []
    assert pub_sub.sent == sent
