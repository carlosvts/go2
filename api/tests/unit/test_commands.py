"""Testes de `SportCommand` e dos objetos de valor de movimento."""

import math
from enum import auto

import pytest

from app.exceptions import InvalidCommandError
from app.robot.commands import MoveCommand, MoveLimits, SportCommand


class _Sample(SportCommand):
    hello = auto()
    finger_heart = auto()
    dance1 = auto()


@pytest.fixture
def limits() -> MoveLimits:
    return MoveLimits(max_vx=1.0, max_vy=1.0, max_vyaw=2.0, max_duration_s=3.0)


# ─── SportCommand ──────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("member", "value", "sport_cmd"),
    [
        (_Sample.hello, "hello", "Hello"),
        (_Sample.finger_heart, "finger_heart", "FingerHeart"),
        (_Sample.dance1, "dance1", "Dance1"),
    ],
)
def test_auto_gera_valor_igual_ao_nome_e_sport_cmd_em_camel_case(
    member: SportCommand, value: str, sport_cmd: str
) -> None:
    assert member.value == value
    assert member.sport_cmd == sport_cmd


def test_valor_continua_snake_case_ao_converter_para_str() -> None:
    """O JSON da request usa `snake_case`; só `sport_cmd` é CamelCase."""
    assert str(_Sample.finger_heart) == "finger_heart"


# ─── MoveCommand ───────────────────────────────────────────────────────────


def test_move_valido_expoe_parametro_x_y_z(limits: MoveLimits) -> None:
    move = MoveCommand(vx=0.3, vy=-0.1, vyaw=0.5, duration_s=1.0, limits=limits)

    assert move.parameter == {"x": 0.3, "y": -0.1, "z": 0.5}


def test_move_aceita_exatamente_o_teto(limits: MoveLimits) -> None:
    MoveCommand(vx=1.0, vy=-1.0, vyaw=2.0, duration_s=3.0, limits=limits)


@pytest.mark.parametrize(
    ("campos", "mensagem"),
    [
        ({"vx": 1.1}, "vx"),
        ({"vy": -1.1}, "vy"),
        ({"vyaw": 2.1}, "vyaw"),
        ({"duration_s": 3.1}, "GO2_MOVE_MAX_DURATION_S"),
        ({"duration_s": 0.0}, "positivo"),
        ({"duration_s": -1.0}, "positivo"),
    ],
)
def test_move_fora_dos_limites_levanta_na_construcao(
    limits: MoveLimits, campos: dict[str, float], mensagem: str
) -> None:
    valores = {"vx": 0.0, "vy": 0.0, "vyaw": 0.0, "duration_s": 1.0} | campos

    with pytest.raises(InvalidCommandError, match=mensagem):
        MoveCommand(**valores, limits=limits)


def test_move_lista_todas_as_velocidades_excedidas(limits: MoveLimits) -> None:
    with pytest.raises(InvalidCommandError, match="vx, vy"):
        MoveCommand(vx=9.0, vy=9.0, vyaw=0.0, duration_s=1.0, limits=limits)


@pytest.mark.parametrize("valor", [math.nan, math.inf, -math.inf])
@pytest.mark.parametrize("campo", ["vx", "vy", "vyaw", "duration_s"])
def test_move_rejeita_valores_nao_finitos(
    limits: MoveLimits, campo: str, valor: float
) -> None:
    """NaN compara falso com qualquer teto, então precisa de checagem própria."""
    valores = {"vx": 0.0, "vy": 0.0, "vyaw": 0.0, "duration_s": 1.0} | {campo: valor}

    with pytest.raises(InvalidCommandError, match="finito"):
        MoveCommand(**valores, limits=limits)


def test_invalid_command_error_e_um_value_error(limits: MoveLimits) -> None:
    with pytest.raises(ValueError, match="vx"):
        MoveCommand(vx=9.0, vy=0.0, vyaw=0.0, duration_s=1.0, limits=limits)
