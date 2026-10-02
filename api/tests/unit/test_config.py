"""Testes de `Settings`: o objeto se recusa a existir inválido."""

import pytest
from pydantic import ValidationError

from app.config import ConnectionMethod, Settings


def test_local_sta_sem_ip_nem_serial_nao_constroi() -> None:
    with pytest.raises(ValidationError, match="GO2_ROBOT_IP"):
        Settings(_env_file=None, connection_method=ConnectionMethod.local_sta)


@pytest.mark.parametrize(
    ("campo", "valor"),
    [("robot_ip", "192.168.1.50"), ("robot_serial_number", "B42D0000")],
)
def test_local_sta_aceita_ip_ou_serial(campo: str, valor: str) -> None:
    settings = Settings.model_validate({campo: valor})

    assert settings.connection_method is ConnectionMethod.local_sta


def test_local_ap_dispensa_ip_e_serial() -> None:
    Settings(_env_file=None, connection_method=ConnectionMethod.local_ap)


@pytest.mark.parametrize(
    ("campo", "valor"),
    [
        ("move_rate_hz", 19.9),
        ("move_rate_hz", 50.1),
        ("request_timeout_s", 0),
        ("move_max_duration_s", 0),
        ("move_max_duration_s", 301),
        ("max_vx", 0),
        ("max_vy", -1),
        ("max_vyaw", 0),
    ],
)
def test_valores_fora_da_faixa_nao_constroem(campo: str, valor: float) -> None:
    with pytest.raises(ValidationError):
        Settings.model_validate({"robot_ip": "192.168.1.50", campo: valor})


def test_le_variaveis_de_ambiente_com_prefixo_go2(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GO2_CONNECTION_METHOD", "LocalAP")
    monkeypatch.setenv("GO2_MAX_VX", "0.4")
    monkeypatch.setenv("GO2_CONNECT_ON_STARTUP", "false")

    settings = Settings(_env_file=None)

    assert settings.connection_method is ConnectionMethod.local_ap
    assert settings.max_vx == pytest.approx(0.4)
    assert settings.connect_on_startup is False


def test_settings_e_imutavel() -> None:
    settings = Settings(_env_file=None, robot_ip="192.168.1.50")

    with pytest.raises(ValidationError):
        settings.max_vx = 9.0  # type: ignore[misc]
