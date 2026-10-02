"""Testes de `SportRequestBuilder`."""

import json

from app.robot.envelope import SportRequestBuilder


def test_envelope_sem_parametro_tem_parameter_vazio() -> None:
    envelope = SportRequestBuilder.build(1004)

    assert envelope["header"]["identity"]["api_id"] == 1004
    assert envelope["parameter"] == ""


def test_dict_vira_string_json() -> None:
    envelope = SportRequestBuilder.build(1008, {"x": 0.1, "y": 0.0, "z": 0.2})

    assert isinstance(envelope["parameter"], str)
    assert json.loads(envelope["parameter"]) == {"x": 0.1, "y": 0.0, "z": 0.2}


def test_string_passa_direto_sem_duplo_encode() -> None:
    assert SportRequestBuilder.build(1, '{"data": 1}')["parameter"] == '{"data": 1}'


def test_id_de_correlacao_cabe_em_int32_com_jitter() -> None:
    limite = 2_147_483_648 + 1000

    for _ in range(50):
        identificador = SportRequestBuilder.build(1)["header"]["identity"]["id"]
        assert 0 <= identificador <= limite
