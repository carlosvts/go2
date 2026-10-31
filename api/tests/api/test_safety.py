"""Testes de `PUT` e `GET /safety/obstacle-avoidance`."""

import pytest
from fastapi.testclient import TestClient

from app.robot.unitree import DATA_CHANNEL_TYPE, OBSTACLES_AVOID_API, RTC_TOPIC
from tests.fakes import FakePubSub

URL = "/safety/obstacle-avoidance"


@pytest.mark.parametrize("enabled", [True, False])
def test_put_envia_switch_set_no_topico_do_desvio(
    client: TestClient, pub_sub: FakePubSub, *, enabled: bool
) -> None:
    resposta = client.put(URL, json={"enabled": enabled})

    assert resposta.status_code == 202
    assert resposta.json() == {"accepted": True, "cmd": "ObstacleAvoidance"}
    (enviado,) = pub_sub.sent
    assert enviado["topic"] == RTC_TOPIC["OBSTACLES_AVOID"]
    assert enviado["topic"] == "rt/api/obstacles_avoid/request"
    assert enviado["type"] == DATA_CHANNEL_TYPE["REQUEST"]
    assert pub_sub.api_ids == [OBSTACLES_AVOID_API["SWITCH_SET"]] == [1001]
    # A API diz `enabled`; o robô espera `enable`.
    assert pub_sub.parameter_of(0) == {"enable": enabled}


@pytest.mark.parametrize(
    "corpo", [{}, {"enabled": "sim"}, {"enabled": 1}, {"enable": True}]
)
def test_put_rejeita_corpo_invalido(
    client: TestClient, pub_sub: FakePubSub, corpo: dict[str, object]
) -> None:
    assert client.put(URL, json=corpo).status_code == 422
    assert pub_sub.sent == []


def test_put_nao_interrompe_o_move_em_curso(
    client: TestClient, pub_sub: FakePubSub
) -> None:
    move = {"vx": 0.3, "vy": 0.0, "vyaw": 0.0, "duration_s": 1.0}
    assert client.post("/commands/move", json=move).status_code == 202

    assert client.put(URL, json={"enabled": True}).status_code == 202

    topicos = [msg["topic"] for msg in pub_sub.sent]
    assert topicos[0] == RTC_TOPIC["SPORT_MOD"]
    assert topicos[-1] == RTC_TOPIC["OBSTACLES_AVOID"]


def test_put_sem_robo_responde_503(offline_client: TestClient) -> None:
    assert offline_client.put(URL, json={"enabled": True}).status_code == 503


def test_get_envia_switch_get_e_devolve_enabled_e_raw(
    client: TestClient, pub_sub: FakePubSub
) -> None:
    pub_sub.response = {"data": {"data": {"enable": True}}}

    resposta = client.get(URL)

    assert resposta.status_code == 200
    assert resposta.json() == {"enabled": True, "raw": {"data": {"enable": True}}}
    (enviado,) = pub_sub.sent
    assert enviado["topic"] == RTC_TOPIC["OBSTACLES_AVOID"]
    assert enviado["options"] == {"api_id": OBSTACLES_AVOID_API["SWITCH_GET"]}
    assert enviado["options"]["api_id"] == 1002


def test_get_com_formato_desconhecido_devolve_enabled_nulo(
    client: TestClient, pub_sub: FakePubSub
) -> None:
    pub_sub.response = {"data": {"algo_inesperado": 9}}

    corpo = client.get(URL).json()

    assert corpo == {"enabled": None, "raw": {"algo_inesperado": 9}}


def test_get_sem_resposta_do_robo_responde_504(
    client: TestClient, pub_sub: FakePubSub
) -> None:
    pub_sub.hang_on_request = True

    assert client.get(URL).status_code == 504


def test_get_sem_robo_responde_503(offline_client: TestClient) -> None:
    assert offline_client.get(URL).status_code == 503
