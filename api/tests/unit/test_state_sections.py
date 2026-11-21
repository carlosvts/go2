"""Seções de estado do `/status` (F-004 A1, A2)."""

import logging
import math
from datetime import UTC, datetime
from typing import Any

import pytest

from app.robot.connection import ConnectionSnapshot, ConnectionState
from app.robot.state import StateCache
from app.robot.unitree import RTC_TOPIC
from tests.fakes import FakePubSub
from tests.state_payloads import (
    low_state,
    multiple_state,
    multiple_state_dict,
    sport_state,
)

CONEXAO = ConnectionSnapshot(
    ConnectionState.connected, datetime(2026, 11, 22, 12, 0, tzinfo=UTC)
)


class _Clock:
    def __init__(self, now: float) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock() -> _Clock:
    return _Clock(100.0)


@pytest.fixture
def cache(clock: _Clock) -> StateCache:
    return StateCache(clock=clock, wall_clock=_Clock(1_763_380_000.0))


def _status(cache: StateCache) -> Any:
    return cache.snapshot(connected=True, connection=CONEXAO, errors=None)


def _feed(cache: StateCache, **sources: Any) -> None:
    if "low" in sources:
        cache.on_low_state({"data": sources["low"]})
    if "sport" in sources:
        cache.on_sport_state({"data": sources["sport"]})
    if "multi" in sources:
        cache.on_multiple_state({"data": sources["multi"]})


# ─── A1 ────────────────────────────────────────────────────────────────────


def test_attach_assina_tambem_o_multiple_state(cache: StateCache) -> None:
    pub_sub = FakePubSub()

    cache.attach(pub_sub)

    assert set(pub_sub.subscriptions) == {
        RTC_TOPIC["SPORT_MOD_STATE"],
        RTC_TOPIC["LOW_STATE"],
        RTC_TOPIC["MULTIPLE_STATE"],
    }


def test_a1_secoes_renomeadas_conforme_a_tabela(cache: StateCache) -> None:
    _feed(cache, low=low_state(), sport=sport_state(), multi=multiple_state())

    status = _status(cache)

    assert status.battery == {
        "percent": 87,
        "voltage_v": 28.5,
        "current_ma": -1500,
        "cycles": 12,
        "temperatures_c": {"bq": 30, "mcu": 32},
    }
    assert status.imu == {
        "rpy": [0.01, -0.02, 1.57],
        "quaternion": [1.0, 0.0, 0.0, 0.0],
        "gyroscope": [0.0, 0.1, 0.0],
        "accelerometer": [0.0, 0.0, 9.8],
        "temperature": 40,
    }
    assert status.motion == {
        "mode": 1,
        "progress": 0.5,
        "gait_type": 1,
        "body_height": 0.32,
        "foot_raise_height": 0.09,
        "position": [1.0, 2.0, 0.3],
        "velocity": [0.1, 0.0, 0.0],
        "yaw_speed": 0.05,
        "range_obstacle": [1.5, 2.0, 0.8, 3.0],
        "foot_force": [100, 110, 95, 105],
    }
    assert status.motors == [
        {"q": 0.1, "temperature_c": 35, "lost": 0},
        {"q": -0.2, "temperature_c": 36.5, "lost": 2},
    ]
    assert status.body_temperature_c == 41
    assert status.settings == {
        "body_height": 0.32,
        "brightness": 5,
        "foot_raise_height": 0.09,
        "obstacle_avoidance": True,
        "speed_level": 1,
        "uwb": False,
        "volume": 7,
    }


def test_a1_campos_antigos_iguais_e_derivados_da_mesma_extracao(
    cache: StateCache,
) -> None:
    _feed(cache, low=low_state(), sport=sport_state())

    status = _status(cache)

    assert status.battery_percent == 87
    assert status.mode == 1
    assert status.battery["percent"] == status.battery_percent
    assert status.motion["mode"] == status.mode


@pytest.mark.parametrize(
    "low",
    [{"bms_state": {"soc": 55}}, {"bms": {"soc": 55}}, {"soc": 55}],
)
def test_a1_percent_segue_os_tres_caminhos_de_hoje(
    cache: StateCache, low: dict[str, Any]
) -> None:
    _feed(cache, low=low)

    status = _status(cache)

    assert status.battery_percent == 55
    assert status.battery["percent"] == 55


def test_a1_idade_do_multiple_state(cache: StateCache, clock: _Clock) -> None:
    _feed(cache, multi=multiple_state())
    clock.now += 1.5

    assert _status(cache).multiple_state_age_s == pytest.approx(1.5)


def test_a1_raw_inclui_o_multiple_state_decodificado(cache: StateCache) -> None:
    _feed(cache, multi=multiple_state())

    assert cache.raw["multiple_state"] == multiple_state_dict()


def test_a1_multiple_state_ja_em_dict_tambem_e_aceito(cache: StateCache) -> None:
    _feed(cache, multi=multiple_state_dict(volume=3))

    assert _status(cache).settings["volume"] == 3


def test_a1_flags_zero_e_um_viram_bool(cache: StateCache) -> None:
    _feed(cache, multi=multiple_state(obstaclesAvoidSwitch=1, uwbSwitch=False))

    settings = _status(cache).settings

    assert settings["obstacle_avoidance"] is True
    assert settings["uwb"] is False


# ─── A2 ────────────────────────────────────────────────────────────────────


def test_a2_topico_que_nunca_chegou_deixa_a_secao_null(cache: StateCache) -> None:
    status = _status(cache)

    assert status.battery is None
    assert status.imu is None
    assert status.motion is None
    assert status.motors is None
    assert status.body_temperature_c is None
    assert status.settings is None
    assert status.multiple_state_age_s is None


@pytest.mark.parametrize(
    ("section", "field", "low"),
    [
        ("battery", "voltage_v", low_state(power_v="28")),  # tipo errado
        ("battery", "voltage_v", low_state(power_v=True)),  # bool não é número
        ("battery", "voltage_v", low_state(power_v=math.nan)),
        ("battery", "voltage_v", low_state(power_v=math.inf)),
        ("battery", "current_ma", low_state(bms_state={"soc": 80})),  # ausente
        ("battery", "cycles", low_state(bms_state={"soc": 80, "cycle": 1.5})),
    ],
)
def test_a2_campo_ruim_da_bateria_vira_null_so_ele(
    cache: StateCache, section: str, field: str, low: dict[str, Any]
) -> None:
    _feed(cache, low=low)

    value = getattr(_status(cache), section)

    assert value[field] is None
    assert value["percent"] is not None or field == "percent"


def test_a2_percent_bool_vira_null(cache: StateCache) -> None:
    _feed(cache, low={"bms_state": {"soc": True}})

    status = _status(cache)

    assert status.battery_percent is None
    assert status.battery["percent"] is None


@pytest.mark.parametrize(
    "rpy",
    [
        [0.0, math.nan, 0.0],  # não finito
        [0.0, 0.0],  # tamanho errado
        [0.0, 0.0, 0.0, 0.0],
        [0.0, True, 0.0],  # bool
        "0,0,0",
        None,
    ],
)
def test_a2_rpy_ruim_vira_null_e_o_resto_da_imu_fica(
    cache: StateCache, rpy: object
) -> None:
    imu = sport_state()["imu_state"] | {"rpy": rpy}
    _feed(cache, sport=sport_state(imu_state=imu))

    status = _status(cache)

    assert status.imu["rpy"] is None
    assert status.imu["quaternion"] == [1.0, 0.0, 0.0, 0.0]
    assert status.motion["mode"] == 1


def test_a2_lista_sem_tamanho_fixo_aceita_qualquer_tamanho(cache: StateCache) -> None:
    _feed(cache, sport=sport_state(range_obstacle=[1.0], foot_force=[1, 2, 3, 4, 5]))

    motion = _status(cache).motion

    assert motion["range_obstacle"] == [1.0]
    assert motion["foot_force"] == [1, 2, 3, 4, 5]


def test_a2_item_ruim_de_motors_vira_null_sem_zerar_a_lista(
    cache: StateCache,
) -> None:
    motors = [
        {"q": 0.1, "temperature": 35, "lost": 0},
        "lixo",
        {"q": math.nan, "temperature": 30, "lost": 1},
    ]
    _feed(cache, low=low_state(motor_state=motors))

    assert _status(cache).motors == [
        {"q": 0.1, "temperature_c": 35, "lost": 0},
        None,
        {"q": None, "temperature_c": 30, "lost": 1},
    ]


def test_a2_motors_que_nao_e_lista_vira_null(cache: StateCache) -> None:
    _feed(cache, low=low_state(motor_state={"q": 1}))

    status = _status(cache)

    assert status.motors is None
    assert status.battery["percent"] == 87


def test_a2_multiple_state_que_nao_e_json_deixa_settings_null(
    cache: StateCache, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING, logger="app.robot.state"):
        _feed(cache, multi="{não é json")

    assert _status(cache).settings is None
    assert "MULTIPLE_STATE" in caplog.text


def test_a2_flag_com_valor_estranho_vira_null(cache: StateCache) -> None:
    _feed(cache, multi=multiple_state(obstaclesAvoidSwitch=2, uwbSwitch="on"))

    settings = _status(cache).settings

    assert settings["obstacle_avoidance"] is None
    assert settings["uwb"] is None
    assert settings["volume"] == 7


def test_a2_inteiro_enorme_em_campo_float_vira_null(cache: StateCache) -> None:
    _feed(cache, low=low_state(power_v=10**400))

    assert _status(cache).battery["voltage_v"] is None
