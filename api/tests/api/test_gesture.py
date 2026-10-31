"""Testes de `POST /commands/gesture`."""

import pytest
from fastapi.testclient import TestClient

from app.robot.unitree import SPORT_CMD
from tests.fakes import FakePubSub

GESTOS = [
    ("hello", "Hello"),
    ("stretch", "Stretch"),
    ("finger_heart", "FingerHeart"),
    ("wiggle_hips", "WiggleHips"),
    ("content", "Content"),
    ("dance1", "Dance1"),
    ("dance2", "Dance2"),
    ("scrape", "Scrape"),
    ("pose", "Pose"),
]


@pytest.mark.parametrize(("cmd", "esperado"), GESTOS)
def test_gesture_aceita_todo_o_enum(
    client: TestClient, pub_sub: FakePubSub, cmd: str, esperado: str
) -> None:
    resposta = client.post("/commands/gesture", json={"cmd": cmd})

    assert resposta.status_code == 202
    assert resposta.json() == {"accepted": True, "cmd": esperado}
    assert pub_sub.api_ids == [SPORT_CMD[esperado]]


def test_gesture_rejeita_trick(client: TestClient, pub_sub: FakePubSub) -> None:
    """Tricks têm risco de queda e entram só em endpoint próprio."""
    resposta = client.post("/commands/gesture", json={"cmd": "front_flip"})

    assert resposta.status_code == 422
    assert pub_sub.sent == []


def test_gesture_nao_aceita_postura(client: TestClient) -> None:
    assert client.post("/commands/gesture", json={"cmd": "sit"}).status_code == 422


def test_gesture_sem_robo_responde_503(offline_client: TestClient) -> None:
    resposta = offline_client.post("/commands/gesture", json={"cmd": "hello"})

    assert resposta.status_code == 503
