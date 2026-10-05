"""Testes de `GET /status`."""

from datetime import datetime

from fastapi.testclient import TestClient

from app.robot.unitree import RTC_TOPIC
from tests.fakes import FakeConnectionFactory, FakePubSub


def test_status_com_robo_desligado_responde_200(offline_client: TestClient) -> None:
    """`/status` é o que distingue "robô fora" de "API fora" — nunca dá 503."""
    resposta = offline_client.get("/status")

    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["connected"] is False
    assert corpo["state"] == "disconnected"
    assert corpo["battery_percent"] is None


def test_status_conectado(client: TestClient, pub_sub: FakePubSub) -> None:
    pub_sub.publish_state(RTC_TOPIC["LOW_STATE"], {"bms_state": {"soc": 42}})

    corpo = client.get("/status").json()

    assert corpo["connected"] is True
    assert corpo["battery_percent"] == 42
    assert corpo["raw"] is None  # só com ?raw=true


def test_status_raw_expoe_payload_cru(client: TestClient, pub_sub: FakePubSub) -> None:
    pub_sub.publish_state(RTC_TOPIC["SPORT_MOD_STATE"], {"mode": 3, "extra": 1})

    corpo = client.get("/status", params={"raw": True}).json()

    assert corpo["raw"]["sport_mode_state"] == {"mode": 3, "extra": 1}
    assert corpo["mode"] == 3


def test_status_sem_conectar_na_subida_responde_200(
    unconnected_client: TestClient,
) -> None:
    corpo = unconnected_client.get("/status").json()

    assert corpo["connected"] is False


def test_status_conectado_expoe_state_e_since(client: TestClient) -> None:
    corpo = client.get("/status").json()

    assert corpo["state"] == "connected"
    assert datetime.fromisoformat(corpo["since"]).tzinfo is not None


def test_status_sem_conectar_na_subida_fica_disconnected(
    unconnected_client: TestClient,
) -> None:
    corpo = unconnected_client.get("/status").json()

    assert corpo["state"] == "disconnected"


def test_status_reflete_a_queda_e_continua_200(
    client: TestClient, factory: FakeConnectionFactory
) -> None:
    antes = client.get("/status").json()
    assert client.portal is not None
    # O evento do aiortc chega na thread do event loop da app.
    client.portal.call(factory.connection.pc.emit_state, "failed")

    resposta = client.get("/status")

    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["state"] == "disconnected"
    assert datetime.fromisoformat(corpo["since"]) >= datetime.fromisoformat(
        antes["since"]
    )
    # `connected` segue `is_connected`, que a lib não zera em `failed`.
    assert corpo["connected"] is True
