"""Testes de `POST /commands/posture`."""

import pytest
from fastapi.testclient import TestClient

from app.robot.unitree import SPORT_CMD
from tests.fakes import FakePubSub

POSTURAS = [
    ("stand_up", "StandUp"),
    ("stand_down", "StandDown"),
    ("sit", "Sit"),
    ("rise_sit", "RiseSit"),
    ("balance_stand", "BalanceStand"),
    ("recovery_stand", "RecoveryStand"),
    ("damp", "Damp"),
]


@pytest.mark.parametrize(("cmd", "esperado"), POSTURAS)
def test_posture_aceita_todo_o_enum(
    client: TestClient, pub_sub: FakePubSub, cmd: str, esperado: str
) -> None:
    resposta = client.post("/commands/posture", json={"cmd": cmd})

    assert resposta.status_code == 202
    assert resposta.json() == {"accepted": True, "cmd": esperado}
    assert pub_sub.api_ids == [SPORT_CMD[esperado]]


@pytest.mark.parametrize(
    "corpo",
    [{"cmd": "front_flip"}, {"cmd": "StandUp"}, {"cmd": ""}, {}, {"cmd": 1}],
)
def test_posture_rejeita_corpo_invalido(
    client: TestClient, pub_sub: FakePubSub, corpo: dict[str, object]
) -> None:
    resposta = client.post("/commands/posture", json=corpo)

    assert resposta.status_code == 422
    assert pub_sub.sent == []  # nada chegou ao robô


def test_posture_sem_corpo_responde_422(client: TestClient) -> None:
    assert client.post("/commands/posture").status_code == 422


def test_posture_sem_robo_responde_503(offline_client: TestClient) -> None:
    resposta = offline_client.post("/commands/posture", json={"cmd": "stand_up"})

    assert resposta.status_code == 503
    assert "Sem conexão" in resposta.json()["detail"]
