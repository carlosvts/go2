"""Testes de `ObstacleAvoidanceReading`."""

from typing import Any

import pytest

from app.robot.safety import ObstacleAvoidanceReading


@pytest.mark.parametrize(
    ("data", "enabled"),
    [
        ({"data": {"enable": True}}, True),
        ({"data": {"enable": False}}, False),
        ({"data": '{"enable":true}'}, True),  # JSON em string, como nas esportivas
        ({"data": '{"enable": false}'}, False),
        ({"enable": True}, True),
        ({"data": {"enabled": False}}, False),
        ({"enabled": True}, True),
    ],
)
def test_extrai_o_enable_dos_formatos_plausiveis(
    data: dict[str, Any], *, enabled: bool
) -> None:
    leitura = ObstacleAvoidanceReading.from_response({"data": data})

    assert leitura.enabled is enabled
    assert leitura.raw == data  # o cru vai como chegou, sem decodificar


@pytest.mark.parametrize(
    "resposta",
    [
        {"data": {"algo_inesperado": 9}},
        {"data": {"data": "não é json"}},
        {"data": {"data": {"enable": 1}}},  # só booleano de verdade vale
        {"data": {"data": {"enable": "true"}}},
        {"data": None},
        {},
        None,
        "texto",
    ],
)
def test_formato_desconhecido_vira_none_nunca_valor_inventado(resposta: Any) -> None:
    assert ObstacleAvoidanceReading.from_response(resposta).enabled is None
