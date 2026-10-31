"""Testes da fronteira com a lib da Unitree (sem abrir WebRTC)."""

from typing import Any

import pytest
from unitree_webrtc_connect import WebRTCConnectionMethod

from app.config import ConnectionMethod, Settings
from app.robot import unitree


class _RecordedConnection:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.args = args
        self.kwargs = kwargs


@pytest.fixture
def recorded(monkeypatch: pytest.MonkeyPatch) -> type[_RecordedConnection]:
    monkeypatch.setattr(unitree, "UnitreeWebRTCConnection", _RecordedConnection)
    return _RecordedConnection


def test_local_sta_repassa_ip_e_serial(recorded: type[_RecordedConnection]) -> None:
    settings = Settings(
        _env_file=None,
        connection_method=ConnectionMethod.local_sta,
        robot_ip="192.168.1.50",
        robot_serial_number="B42D0000",
    )

    connection = unitree.UnitreeConnectionFactory(settings)()

    assert isinstance(connection, recorded)
    assert connection.args == (WebRTCConnectionMethod.LocalSTA,)
    assert connection.kwargs == {"ip": "192.168.1.50", "serialNumber": "B42D0000"}


def test_local_ap_usa_o_metodo_local_ap(recorded: type[_RecordedConnection]) -> None:
    settings = Settings(_env_file=None, connection_method=ConnectionMethod.local_ap)

    connection = unitree.UnitreeConnectionFactory(settings)()

    assert isinstance(connection, recorded)
    assert connection.args == (WebRTCConnectionMethod.LocalAP,)


def test_cada_chamada_cria_uma_conexao_nova(
    recorded: type[_RecordedConnection],
) -> None:
    factory = unitree.UnitreeConnectionFactory(
        Settings(_env_file=None, robot_serial_number="B42D0000")
    )

    assert factory() is not factory()
