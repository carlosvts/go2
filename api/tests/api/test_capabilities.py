"""Testes de `GET /capabilities`."""

from fastapi.testclient import TestClient

from app.robot.unitree import SPORT_CMD
from tests.fakes import FakePubSub

# Valores válidos para os campos que não são `cmd`.
EXEMPLO = {"vx": 0.1, "vy": 0.0, "vyaw": 0.0, "duration_s": 0.1, "level": 1}


def test_capabilities_responde_sem_robo(offline_client: TestClient) -> None:
    resposta = offline_client.get("/capabilities")

    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["version"]
    assert corpo["commands"]
    # Mesma lista → mesmo hash.
    assert offline_client.get("/capabilities").json()["version"] == corpo["version"]


def test_todo_comando_listado_e_aceito_pela_rota(
    client: TestClient, pub_sub: FakePubSub
) -> None:
    comandos = client.get("/capabilities").json()["commands"]

    for comando in comandos:
        corpo = {
            campo: comando["name"] if campo == "cmd" else EXEMPLO[campo]
            for campo in comando["params"]
        }
        resposta = client.request(
            comando["method"], comando["endpoint"], json=corpo or None
        )

        assert resposta.status_code == 202, comando
        assert resposta.json()["cmd"] == comando["sport_cmd"]
        assert SPORT_CMD[comando["sport_cmd"]] in pub_sub.api_ids


def test_capabilities_distingue_stop_de_damp(client: TestClient) -> None:
    comandos = {c["name"]: c for c in client.get("/capabilities").json()["commands"]}

    assert comandos["stop"]["sport_cmd"] == "StopMove"
    assert comandos["damp"]["sport_cmd"] == "Damp"
    assert {"move", "speed"} <= comandos.keys()
