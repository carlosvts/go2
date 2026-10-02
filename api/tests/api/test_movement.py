"""Testes de `POST /commands/move` e `POST /commands/stop`."""

import json
import math
import time

import pytest
from fastapi.testclient import TestClient

from app.robot.unitree import SPORT_CMD
from tests.fakes import FakePubSub

CORPO_VALIDO = {"vx": 0.5, "vy": 0.0, "vyaw": 0.2, "duration_s": 0.05}


def test_move_aceito(client: TestClient, pub_sub: FakePubSub) -> None:
    resposta = client.post("/commands/move", json=CORPO_VALIDO)

    assert resposta.status_code == 202
    assert resposta.json() == {"accepted": True, "cmd": "Move"}
    assert pub_sub.parameter_of(0) == {"x": 0.5, "y": 0.0, "z": 0.2}


def test_move_para_sozinho_no_fim_da_janela(
    client: TestClient, pub_sub: FakePubSub
) -> None:
    client.post("/commands/move", json=CORPO_VALIDO)
    time.sleep(0.3)

    assert pub_sub.api_ids[-1] == SPORT_CMD["StopMove"]


@pytest.mark.parametrize(
    ("campo", "valor"),
    [("vx", 9.0), ("vy", -9.0), ("vyaw", 9.0), ("duration_s", 999.0)],
)
def test_move_acima_dos_tetos_responde_422_sem_chegar_ao_robo(
    client: TestClient, pub_sub: FakePubSub, campo: str, valor: float
) -> None:
    resposta = client.post("/commands/move", json=CORPO_VALIDO | {campo: valor})

    assert resposta.status_code == 422
    assert isinstance(resposta.json()["detail"], str)
    assert pub_sub.sent == []


def test_move_informa_quais_velocidades_excederam(client: TestClient) -> None:
    resposta = client.post(
        "/commands/move", json=CORPO_VALIDO | {"vx": 9.0, "vyaw": 9.0}
    )

    assert "vx, vyaw" in resposta.json()["detail"]


@pytest.mark.parametrize("duracao", [0, -1])
def test_move_exige_duracao_positiva(client: TestClient, duracao: float) -> None:
    resposta = client.post(
        "/commands/move", json=CORPO_VALIDO | {"duration_s": duracao}
    )

    assert resposta.status_code == 422


@pytest.mark.parametrize("campo", ["vx", "vy", "vyaw", "duration_s"])
@pytest.mark.parametrize("valor", [math.nan, math.inf, -math.inf])
def test_move_rejeita_nan_e_infinito(
    client: TestClient, pub_sub: FakePubSub, campo: str, valor: float
) -> None:
    """NaN escaparia de uma checagem `abs(v) > teto` — e chegaria ao robô."""
    corpo = {"vx": 0.1, "vy": 0.0, "vyaw": 0.0, "duration_s": 1.0} | {campo: valor}

    resposta = client.post(
        "/commands/move",
        content=json.dumps(corpo),
        headers={"Content-Type": "application/json"},
    )

    assert resposta.status_code == 422
    assert pub_sub.sent == []


def test_422_de_validacao_nao_ecoa_o_valor_recebido(client: TestClient) -> None:
    resposta = client.post(
        "/commands/move",
        content='{"vx": NaN, "vy": 0, "vyaw": 0, "duration_s": 1}',
        headers={"Content-Type": "application/json"},
    )

    assert resposta.status_code == 422
    erro = resposta.json()["detail"][0]
    assert erro["loc"] == ["body", "vx"]
    assert "input" not in erro


def test_move_com_campo_faltando_responde_422(client: TestClient) -> None:
    corpo = {"vx": 0.1, "vy": 0.0, "vyaw": 0.0}

    assert client.post("/commands/move", json=corpo).status_code == 422


def test_move_sem_robo_responde_503(offline_client: TestClient) -> None:
    assert offline_client.post("/commands/move", json=CORPO_VALIDO).status_code == 503


def test_tetos_vem_da_configuracao(client: TestClient) -> None:
    """A fixture configura `max_vx=1.0`: 1.0 passa, 1.01 não."""
    assert (
        client.post("/commands/move", json=CORPO_VALIDO | {"vx": 1.0}).status_code
        == 202
    )
    assert (
        client.post("/commands/move", json=CORPO_VALIDO | {"vx": 1.01}).status_code
        == 422
    )


def test_stop(client: TestClient, pub_sub: FakePubSub) -> None:
    resposta = client.post("/commands/stop")

    assert resposta.status_code == 202
    assert resposta.json() == {"accepted": True, "cmd": "StopMove"}
    assert pub_sub.api_ids == [SPORT_CMD["StopMove"]]


def test_stop_sem_robo_responde_503(offline_client: TestClient) -> None:
    assert offline_client.post("/commands/stop").status_code == 503
