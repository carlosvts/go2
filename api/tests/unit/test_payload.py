"""Testes de `PayloadReader`."""

from typing import Any

import pytest

from app.robot.payload import PayloadReader


def test_devolve_o_primeiro_caminho_existente() -> None:
    payload = {"bms": {"soc": 10}, "soc": 99}

    assert PayloadReader.first_path(payload, ("bms_state", "soc"), ("bms", "soc")) == 10


def test_respeita_a_ordem_dos_caminhos() -> None:
    payload = {"a": 1, "b": 2}

    assert PayloadReader.first_path(payload, ("b",), ("a",)) == 2


@pytest.mark.parametrize("payload", [None, 3, "texto", [], {}, {"a": {"b": 1}}])
def test_devolve_none_quando_nenhum_caminho_bate(payload: Any) -> None:
    assert PayloadReader.first_path(payload, ("x",), ("a", "c")) is None


def test_caminho_atravessando_valor_que_nao_e_dict_devolve_none() -> None:
    assert PayloadReader.first_path({"a": 5}, ("a", "b")) is None


def test_valor_none_nao_conta_como_encontrado() -> None:
    assert PayloadReader.first_path({"a": None, "b": 7}, ("a",), ("b",)) == 7
