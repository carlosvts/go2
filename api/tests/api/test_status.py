"""Testes de `GET /status`."""

from fastapi.testclient import TestClient

from app.robot.unitree import RTC_TOPIC
from tests.fakes import FakePubSub


def test_status_com_robo_desligado_responde_200(offline_client: TestClient) -> None:
    """`/status` é o que distingue "robô fora" de "API fora" — nunca dá 503."""
    resposta = offline_client.get("/status")

    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["connected"] is False
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
