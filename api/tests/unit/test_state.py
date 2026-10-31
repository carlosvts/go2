"""Testes de `StateCache`."""

from datetime import UTC, datetime
from typing import Any

import pytest

from app.robot.connection import ConnectionSnapshot, ConnectionState
from app.robot.state import StateCache
from app.robot.unitree import RTC_TOPIC
from tests.fakes import FakePubSub

CONEXAO = ConnectionSnapshot(
    ConnectionState.connected, datetime(2026, 10, 5, 12, 0, tzinfo=UTC)
)


class _Clock:
    """Relógio manual para tornar as idades determinísticas."""

    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock() -> _Clock:
    return _Clock()


@pytest.fixture
def cache(clock: _Clock) -> StateCache:
    return StateCache(clock=clock)


def test_attach_assina_os_dois_topicos_de_estado(cache: StateCache) -> None:
    pub_sub = FakePubSub()

    cache.attach(pub_sub)

    assert set(pub_sub.subscriptions) == {
        RTC_TOPIC["SPORT_MOD_STATE"],
        RTC_TOPIC["LOW_STATE"],
    }


def test_sem_estado_recebido_tudo_e_none(cache: StateCache) -> None:
    status = cache.snapshot(connected=True, connection=CONEXAO)

    assert status.connected is True
    assert status.battery_percent is None
    assert status.mode is None
    assert status.sport_state_age_s is None
    assert status.low_state_age_s is None


@pytest.mark.parametrize(
    "payload",
    [
        {"bms_state": {"soc": 87}},
        {"bms": {"soc": 87}},
        {"soc": 87},
    ],
)
def test_bateria_lida_de_qualquer_caminho_conhecido(
    cache: StateCache, payload: dict[str, Any]
) -> None:
    cache.on_low_state({"data": payload})

    assert cache.snapshot(connected=True, connection=CONEXAO).battery_percent == 87


def test_modo_e_idade_do_estado(cache: StateCache, clock: _Clock) -> None:
    cache.on_sport_state({"data": {"mode": 1}})
    clock.now += 2.5

    status = cache.snapshot(connected=True, connection=CONEXAO)

    assert status.mode == 1
    assert status.sport_state_age_s == pytest.approx(2.5)
    assert status.low_state_age_s is None


def test_campo_com_tipo_inesperado_vira_none(cache: StateCache) -> None:
    cache.on_low_state({"data": {"soc": "alto"}})
    cache.on_sport_state({"data": {"mode": "x"}})

    status = cache.snapshot(connected=True, connection=CONEXAO)

    assert status.battery_percent is None
    assert status.mode is None


def test_mensagem_sem_data_limpa_o_cache(cache: StateCache) -> None:
    cache.on_low_state({"data": {"soc": 50}})
    cache.on_low_state({})

    assert cache.snapshot(connected=True, connection=CONEXAO).battery_percent is None


def test_raw_expoe_os_payloads_sem_interpretar(cache: StateCache) -> None:
    cache.on_sport_state({"data": {"mode": 3, "extra": 1}})

    assert cache.raw == {
        "sport_mode_state": {"mode": 3, "extra": 1},
        "low_state": None,
    }


def test_snapshot_reflete_o_flag_connected(cache: StateCache) -> None:
    assert cache.snapshot(connected=False, connection=CONEXAO).connected is False


def test_snapshot_inclui_o_estado_publicado_da_conexao(cache: StateCache) -> None:
    status = cache.snapshot(connected=False, connection=CONEXAO)

    assert status.state is ConnectionState.connected
    assert status.since == CONEXAO.since
