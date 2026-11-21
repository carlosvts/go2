"""Regras de `ActiveErrors` com dados malformados (F-004)."""

import math
from typing import Any

import pytest

from app.robot.errors import ActiveErrors

CHANNEL = object()


def _apply(errors: ActiveErrors, msg_type: str, data: Any) -> None:
    errors.on_message(CHANNEL, {"type": msg_type, "data": data})


@pytest.fixture
def errors() -> ActiveErrors:
    return ActiveErrors(wall_clock=lambda: 50.0)


@pytest.mark.parametrize(
    "item",
    [
        [1, 300],  # tamanho errado
        [1, "300", 16],  # origem não inteira
        [1, 300, True],  # bool
        [1, 300, -1],  # negativo
        "lixo",
    ],
)
def test_item_malformado_e_ignorado(errors: ActiveErrors, item: Any) -> None:
    # O bom vem primeiro: como na lib, `data[0]` que não é lista = item único.
    _apply(errors, "errors", [[1, 300, 16], item])

    assert [(e["source"], e["code"]) for e in errors.current or []] == [(300, 16)]


def test_data_que_nao_e_lista_nao_muda_nada(errors: ActiveErrors) -> None:
    _apply(errors, "errors", {"a": 1})

    assert errors.current is None


def test_errors_sem_data_e_fotografia_vazia(errors: ActiveErrors) -> None:
    _apply(errors, "errors", None)

    assert errors.current == []


def test_rm_error_com_lista_desconhecida_continua_desconhecida(
    errors: ActiveErrors,
) -> None:
    _apply(errors, "rm_error", [1, 300, 16])

    assert errors.current is None


@pytest.mark.parametrize("ts", [math.nan, "ontem", True])
def test_robot_ts_ilegivel_vira_null(errors: ActiveErrors, ts: Any) -> None:
    _apply(errors, "add_error", [ts, 300, 16])

    (error,) = errors.current or []
    assert error["robot_ts"] is None
    assert error["seen_at"] == 50.0


def test_fotografia_mantem_o_seen_at_de_quem_ja_estava() -> None:
    now = [10.0]
    errors = ActiveErrors(wall_clock=lambda: now[0])
    _apply(errors, "add_error", [1, 300, 16])
    now[0] = 20.0

    _apply(errors, "errors", [[2, 300, 16], [2, 100, 1], [2, 100, 1]])

    assert [(e["code"], e["seen_at"]) for e in errors.current or []] == [
        (16, 10.0),
        (1, 20.0),
    ]


def test_outros_tipos_sao_ignorados(errors: ActiveErrors) -> None:
    _apply(errors, "msg", [1, 300, 16])

    assert errors.current is None
    assert errors.message_count == 0


def test_ouvinte_com_defeito_nao_impede_os_outros(errors: ActiveErrors) -> None:
    seen: list[Any] = []

    def broken(_errors: Any, _ts: float) -> None:
        raise RuntimeError

    errors.subscribe(broken)
    errors.subscribe(lambda current, _ts: seen.append(current))
    _apply(errors, "add_error", [1, 300, 16])

    assert len(seen) == 1


def test_reset_com_aviso_so_avisa_se_mudou(errors: ActiveErrors) -> None:
    seen: list[Any] = []
    errors.subscribe(lambda current, _ts: seen.append(current))

    errors.reset(notify=True)
    _apply(errors, "errors", [])
    errors.reset(notify=True)

    assert seen == [[], None]
