"""`GET /status` ampliado, com a app real (F-004 A1, A2)."""

import math

from fastapi.testclient import TestClient

from app.robot.unitree import RTC_TOPIC
from tests.fakes import FakePubSub
from tests.state_payloads import (
    low_state,
    multiple_state,
    multiple_state_dict,
    sport_state,
)


def _publish_all(pub_sub: FakePubSub) -> None:
    pub_sub.publish_state(RTC_TOPIC["LOW_STATE"], low_state())
    pub_sub.publish_state(RTC_TOPIC["SPORT_MOD_STATE"], sport_state())
    pub_sub.subscriptions[RTC_TOPIC["MULTIPLE_STATE"]](
        {"type": "msg", "topic": RTC_TOPIC["MULTIPLE_STATE"], "data": multiple_state()}
    )


def test_a1_status_devolve_as_secoes_e_os_campos_antigos(
    client: TestClient, pub_sub: FakePubSub
) -> None:
    _publish_all(pub_sub)

    body = client.get("/status").json()

    assert body["battery_percent"] == 87
    assert body["mode"] == 1
    assert body["battery"]["percent"] == body["battery_percent"]
    assert body["motion"]["mode"] == body["mode"]
    assert body["battery"]["temperatures_c"] == {"bq": 30, "mcu": 32}
    assert body["battery"]["voltage_v"] == 28.5
    assert body["imu"]["rpy"] == [0.01, -0.02, 1.57]
    assert body["motors"][1] == {"q": -0.2, "temperature_c": 36.5, "lost": 2}
    assert body["body_temperature_c"] == 41
    assert body["settings"]["volume"] == 7
    assert body["settings"]["obstacle_avoidance"] is True
    assert body["multiple_state_age_s"] is not None
    assert body["low_state_age_s"] is not None
    assert body["sport_state_age_s"] is not None
    assert body["errors"] is None
    assert body["raw"] is None


def test_a1_raw_traz_o_multiple_state_decodificado(
    client: TestClient, pub_sub: FakePubSub
) -> None:
    _publish_all(pub_sub)

    raw = client.get("/status", params={"raw": True}).json()["raw"]

    assert raw["multiple_state"] == multiple_state_dict()
    assert set(raw) == {"sport_mode_state", "low_state", "multiple_state"}


def test_a2_payload_ruim_responde_200_com_campo_null(
    client: TestClient, pub_sub: FakePubSub
) -> None:
    imu = sport_state()["imu_state"] | {"rpy": [math.nan, 0.0, 0.0]}
    pub_sub.publish_state(RTC_TOPIC["SPORT_MOD_STATE"], sport_state(imu_state=imu))
    pub_sub.publish_state(RTC_TOPIC["LOW_STATE"], low_state(motor_state=[1, 2]))

    response = client.get("/status")

    assert response.status_code == 200
    body = response.json()
    assert body["imu"]["rpy"] is None
    assert body["motors"] == [None, None]
    assert body["settings"] is None


def test_a2_robo_desligado_tem_todas_as_secoes_null(
    offline_client: TestClient,
) -> None:
    body = offline_client.get("/status").json()

    for key in (
        "battery",
        "imu",
        "motion",
        "motors",
        "body_temperature_c",
        "settings",
        "errors",
        "multiple_state_age_s",
    ):
        assert body[key] is None, key
