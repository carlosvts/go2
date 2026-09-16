"""Testes dos endpoints HTTP."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from unitree_webrtc_connect import RTC_TOPIC, SPORT_CMD

from app.config import Settings
from app.dependencies import get_robot
from app.main import create_app
from app.robot import RobotConnection


@pytest.fixture
def client(settings: Settings, robot: RobotConnection) -> Iterator[TestClient]:
    app = create_app(settings)
    app.dependency_overrides[get_robot] = lambda: robot
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def offline_client(
    settings: Settings, offline_robot: RobotConnection
) -> Iterator[TestClient]:
    app = create_app(settings)
    app.dependency_overrides[get_robot] = lambda: offline_robot
    with TestClient(app) as test_client:
        yield test_client


# ─── /status ───────────────────────────────────────────────────────────────


def test_status_com_robo_desligado_responde_200(offline_client: TestClient) -> None:
    """`/status` é o que distingue "robô fora" de "API fora" — nunca dá 503."""
    resposta = offline_client.get("/status")

    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["connected"] is False
    assert corpo["battery_percent"] is None


def test_status_conectado(client: TestClient, pub_sub) -> None:
    pub_sub.subscriptions[RTC_TOPIC["LOW_STATE"]](
        {"topic": RTC_TOPIC["LOW_STATE"], "data": {"bms_state": {"soc": 42}}}
    )

    corpo = client.get("/status").json()

    assert corpo["connected"] is True
    assert corpo["battery_percent"] == 42
    assert corpo["raw"] is None  # só com ?raw=true


def test_status_raw_expoe_payload_cru(client: TestClient, pub_sub) -> None:
    pub_sub.subscriptions[RTC_TOPIC["SPORT_MOD_STATE"]](
        {"topic": RTC_TOPIC["SPORT_MOD_STATE"], "data": {"mode": 3, "extra": 1}}
    )

    corpo = client.get("/status", params={"raw": True}).json()

    assert corpo["raw"]["sport_mode_state"] == {"mode": 3, "extra": 1}


# ─── /commands/posture ─────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("cmd", "esperado"),
    [
        ("stand_up", "StandUp"),
        ("stand_down", "StandDown"),
        ("sit", "Sit"),
        ("rise_sit", "RiseSit"),
        ("balance_stand", "BalanceStand"),
        ("recovery_stand", "RecoveryStand"),
        ("damp", "Damp"),
    ],
)
def test_posture_aceita_todo_o_enum(
    client: TestClient, pub_sub, cmd: str, esperado: str
) -> None:
    resposta = client.post("/commands/posture", json={"cmd": cmd})

    assert resposta.status_code == 202
    assert resposta.json() == {"accepted": True, "cmd": esperado}
    assert pub_sub.api_ids == [SPORT_CMD[esperado]]


def test_posture_rejeita_comando_desconhecido(client: TestClient) -> None:
    assert client.post("/commands/posture", json={"cmd": "front_flip"}).status_code == 422


def test_posture_sem_robo_responde_503(offline_client: TestClient) -> None:
    resposta = offline_client.post("/commands/posture", json={"cmd": "stand_up"})

    assert resposta.status_code == 503


# ─── /commands/move ────────────────────────────────────────────────────────


def test_move_aceito(client: TestClient, pub_sub) -> None:
    resposta = client.post(
        "/commands/move",
        json={"vx": 0.5, "vy": 0.0, "vyaw": 0.2, "duration_s": 0.05},
    )

    assert resposta.status_code == 202
    assert pub_sub.parameter_of(0) == {"x": 0.5, "y": 0.0, "yaw": 0.2}


@pytest.mark.parametrize(
    "corpo",
    [
        {"vx": 9.0, "vy": 0.0, "vyaw": 0.0, "duration_s": 1.0},
        {"vx": 0.0, "vy": -9.0, "vyaw": 0.0, "duration_s": 1.0},
        {"vx": 0.0, "vy": 0.0, "vyaw": 9.0, "duration_s": 1.0},
        {"vx": 0.0, "vy": 0.0, "vyaw": 0.0, "duration_s": 999.0},
    ],
)
def test_move_fora_dos_limites_responde_422(
    client: TestClient, pub_sub, corpo: dict
) -> None:
    resposta = client.post("/commands/move", json=corpo)

    assert resposta.status_code == 422
    assert pub_sub.sent == []  # nada chegou ao robô


def test_move_exige_duracao_positiva(client: TestClient) -> None:
    resposta = client.post(
        "/commands/move", json={"vx": 0.1, "vy": 0.0, "vyaw": 0.0, "duration_s": 0}
    )

    assert resposta.status_code == 422


def test_move_sem_robo_responde_503(offline_client: TestClient) -> None:
    resposta = offline_client.post(
        "/commands/move", json={"vx": 0.1, "vy": 0.0, "vyaw": 0.0, "duration_s": 1.0}
    )

    assert resposta.status_code == 503


# ─── /commands/stop ────────────────────────────────────────────────────────


def test_stop(client: TestClient, pub_sub) -> None:
    resposta = client.post("/commands/stop")

    assert resposta.status_code == 202
    assert pub_sub.api_ids == [SPORT_CMD["StopMove"]]


def test_stop_sem_robo_responde_503(offline_client: TestClient) -> None:
    assert offline_client.post("/commands/stop").status_code == 503


# ─── /commands/speed ───────────────────────────────────────────────────────


def test_put_speed(client: TestClient, pub_sub) -> None:
    resposta = client.put("/commands/speed", json={"level": 1})

    assert resposta.status_code == 202
    assert pub_sub.api_ids == [SPORT_CMD["SpeedLevel"]]
    assert pub_sub.parameter_of(0) == {"data": 1}


def test_get_speed(client: TestClient, pub_sub) -> None:
    pub_sub.response = {"data": {"data": -1}}

    corpo = client.get("/commands/speed").json()

    assert corpo["level"] == -1


def test_get_speed_sem_robo_responde_503(offline_client: TestClient) -> None:
    assert offline_client.get("/commands/speed").status_code == 503
