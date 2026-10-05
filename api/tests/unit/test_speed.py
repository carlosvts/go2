"""Testes de `SpeedReading`."""

from typing import Any

import pytest

from app.robot.speed import SpeedReading


@pytest.mark.parametrize(
    ("data", "nivel"),
    [
        ({"data": 2}, 2),
        ({"data": -1}, -1),
        ({"level": 1}, 1),
        ({"speed_level": 0}, 0),
        ({"data": "2"}, 2),
    ],
)
def test_extrai_o_nivel_dos_formatos_conhecidos(data: dict[str, Any], nivel: int) -> None:
    leitura = SpeedReading.from_response({"data": data})

    assert leitura.level == nivel
    assert leitura.raw == data


@pytest.mark.parametrize(
    "resposta",
    [
        {"data": {"algo_inesperado": 9}},
        {"data": {"data": "abc"}},
        {"data": None},
        {},
        None,
        "texto",
    ],
)
def test_formato_desconhecido_vira_none_nunca_valor_inventado(resposta: Any) -> None:
    assert SpeedReading.from_response(resposta).level is None


def test_resposta_crua_acompanha_o_resultado() -> None:
    leitura = SpeedReading.from_response({"data": {"algo_inesperado": 9}})

    assert leitura.raw == {"algo_inesperado": 9}
