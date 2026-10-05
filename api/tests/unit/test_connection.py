"""Testes de `ConnectionStateTracker`."""

from datetime import UTC, datetime, timedelta

import pytest

from app.robot.connection import ConnectionState, ConnectionStateTracker

T0 = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)


class _Clock:
    """Relógio manual: só anda quando o teste manda."""

    def __init__(self) -> None:
        self.now = T0

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


@pytest.fixture
def clock() -> _Clock:
    return _Clock()


@pytest.fixture
def tracker(clock: _Clock) -> ConnectionStateTracker:
    return ConnectionStateTracker(clock)


@pytest.fixture
def received(tracker: ConnectionStateTracker) -> list[dict[str, str]]:
    mensagens: list[dict[str, str]] = []
    tracker.subscribe(mensagens.append)
    return mensagens


def test_comeca_desconectado(tracker: ConnectionStateTracker) -> None:
    assert tracker.current.state is ConnectionState.disconnected
    assert tracker.current.since == T0


def test_since_e_utc_por_padrao() -> None:
    assert ConnectionStateTracker().current.since.tzinfo is UTC


def test_valores_do_enum_sao_o_contrato_publico() -> None:
    assert [estado.value for estado in ConnectionState] == [
        "connected",
        "disconnected",
        "reconnecting",
    ]


def test_update_publica_estado_e_motivo(
    tracker: ConnectionStateTracker, received: list[dict[str, str]]
) -> None:
    tracker.update(ConnectionState.connected, reason="connected")

    assert received == [{"state": "connected", "reason": "connected"}]
    assert tracker.current.state is ConnectionState.connected


def test_update_registra_o_momento_da_transicao(
    tracker: ConnectionStateTracker, clock: _Clock
) -> None:
    clock.advance(5)

    tracker.update(ConnectionState.connected, reason="connected")

    assert tracker.current.since == T0 + timedelta(seconds=5)


def test_estado_repetido_nao_publica_nem_muda_since(
    tracker: ConnectionStateTracker, clock: _Clock, received: list[dict[str, str]]
) -> None:
    tracker.update(ConnectionState.connected, reason="connected")
    clock.advance(5)

    tracker.update(ConnectionState.connected, reason="connected")

    assert len(received) == 1
    assert tracker.current.since == T0


@pytest.mark.parametrize("peer_state", ["failed", "closed", "disconnected"])
def test_queda_do_peer_vira_disconnected(
    tracker: ConnectionStateTracker,
    received: list[dict[str, str]],
    peer_state: str,
) -> None:
    tracker.update(ConnectionState.connected, reason="connected")

    tracker.on_peer_state(peer_state)

    assert received[-1] == {"state": "disconnected", "reason": peer_state}


def test_peer_connected_vira_connected(
    tracker: ConnectionStateTracker, received: list[dict[str, str]]
) -> None:
    tracker.on_peer_state("connected")

    assert received == [{"state": "connected", "reason": "connected"}]


@pytest.mark.parametrize("peer_state", ["new", "connecting", "desconhecido"])
def test_estado_transitorio_do_peer_e_ignorado(
    tracker: ConnectionStateTracker,
    received: list[dict[str, str]],
    peer_state: str,
) -> None:
    tracker.update(ConnectionState.connected, reason="connected")

    tracker.on_peer_state(peer_state)

    assert tracker.current.state is ConnectionState.connected
    assert len(received) == 1


def test_failed_seguido_de_closed_gera_uma_mensagem(
    tracker: ConnectionStateTracker, received: list[dict[str, str]]
) -> None:
    tracker.update(ConnectionState.connected, reason="connected")

    tracker.on_peer_state("failed")
    tracker.on_peer_state("closed")

    assert received[1:] == [{"state": "disconnected", "reason": "failed"}]


def test_oscilacao_publica_todas_as_transicoes(
    tracker: ConnectionStateTracker, received: list[dict[str, str]]
) -> None:
    """Sem debounce: cada transição real vira uma mensagem."""
    for peer_state in ["connected", "disconnected", "connected", "disconnected"]:
        tracker.on_peer_state(peer_state)

    assert [m["state"] for m in received] == [
        "connected",
        "disconnected",
        "connected",
        "disconnected",
    ]


def test_nenhum_estado_do_peer_publica_reconnecting(
    tracker: ConnectionStateTracker, received: list[dict[str, str]]
) -> None:
    for peer_state in ["new", "connecting", "connected", "disconnected", "failed"]:
        tracker.on_peer_state(peer_state)

    assert "reconnecting" not in {m["state"] for m in received}


def test_ouvinte_com_defeito_nao_impede_os_outros(
    tracker: ConnectionStateTracker,
    received: list[dict[str, str]],
    caplog: pytest.LogCaptureFixture,
) -> None:
    def quebrado(_: dict[str, str]) -> None:
        raise RuntimeError("bug no ouvinte")

    tracker.subscribe(quebrado)
    depois: list[dict[str, str]] = []
    tracker.subscribe(depois.append)

    tracker.update(ConnectionState.connected, reason="connected")

    assert len(received) == len(depois) == 1
    assert tracker.current.state is ConnectionState.connected
    assert "Falha num ouvinte" in caplog.text
