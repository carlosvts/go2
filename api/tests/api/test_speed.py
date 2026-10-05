"""Testes de `PUT` e `GET /commands/speed`."""

import pytest
from fastapi.testclient import TestClient

from app.robot.unitree import SPORT_CMD
from tests.fakes import FakePubSub


def test_put_speed(client: TestClient, pub_sub: FakePubSub) -> None:
    resposta = client.put("/commands/speed", json={"level": 1})

    assert resposta.status_code == 202
    assert resposta.json() == {"accepted": True, "cmd": "SpeedLevel"}
    assert pub_sub.api_ids == [SPORT_CMD["SpeedLevel"]]
    assert pub_sub.parameter_of(0) == {"data": 1}


@pytest.mark.parametrize("corpo", [{}, {"level": "alto"}, {"level": 1.5}])
def test_put_speed_rejeita_corpo_invalido(
    client: TestClient, pub_sub: FakePubSub, corpo: dict[str, object]
) -> None:
    assert client.put("/commands/speed", json=corpo).status_code == 422
    assert pub_sub.sent == []


def test_get_speed(client: TestClient, pub_sub: FakePubSub) -> None:
    pub_sub.response = {"data": {"data": -1}}

    corpo = client.get("/commands/speed").json()

    assert corpo == {"level": -1, "raw": {"data": -1}}


def test_get_speed_com_formato_desconhecido_devolve_level_nulo(
    client: TestClient, pub_sub: FakePubSub
) -> None:
    pub_sub.response = {"data": {"algo_inesperado": 9}}

    corpo = client.get("/commands/speed").json()

    assert corpo["level"] is None
    assert corpo["raw"] == {"algo_inesperado": 9}


def test_get_speed_sem_resposta_do_robo_responde_504(
    client: TestClient, pub_sub: FakePubSub
) -> None:
    pub_sub.hang_on_request = True

    assert client.get("/commands/speed").status_code == 504


def test_get_speed_sem_robo_responde_503(offline_client: TestClient) -> None:
    assert offline_client.get("/commands/speed").status_code == 503
