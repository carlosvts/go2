"""Testes de `Settings`: o objeto se recusa a existir inválido."""

from pathlib import Path

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
def test_local_sta_aceita_ip_ou_serial(
    campo: str, valor: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)  # sem o `.env` de quem roda os testes
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


@pytest.mark.parametrize(
    ("campo", "valor"),
    [
        ("video_max_fps", -1),
        ("video_jpeg_quality", 0),
        ("video_jpeg_quality", 101),
        ("video_stall_s", 0),
        ("video_max_clients", -1),
        ("video_client_queue", 0),
        ("video_encode_queue", 0),
    ],
)
def test_a7_config_de_video_fora_da_faixa_nao_constroi(
    campo: str, valor: float
) -> None:
    with pytest.raises(ValidationError):
        Settings.model_validate({"connection_method": "LocalAP", campo: valor})


def test_padroes_de_video_da_spec() -> None:
    settings = Settings(_env_file=None, connection_method=ConnectionMethod.local_ap)

    assert settings.video_max_clients == 2
    assert settings.video_client_queue == 1
    assert settings.video_encode_queue == 1
    assert settings.video_max_fps == 0
    assert settings.video_jpeg_quality == 80
    assert settings.video_stall_s == 3


@pytest.mark.parametrize(
    ("campo", "valor"),
    [
        ("max_volume", -1),
        ("max_volume", 11),
        ("max_brightness", -1),
        ("max_brightness", 11),
        ("led_max_duration_s", 0),
    ],
)
def test_f005_config_de_dispositivo_fora_da_faixa_nao_constroi(
    campo: str, valor: int
) -> None:
    with pytest.raises(ValidationError):
        Settings.model_validate({"connection_method": "LocalAP", campo: valor})


@pytest.mark.parametrize(
    ("campo", "valor"),
    [("state_max_hz", -0.1), ("state_max_hz", -1), ("state_max_clients", -1)],
)
def test_f004_a5_config_de_estado_negativa_impede_a_api_de_subir(
    campo: str, valor: float
) -> None:
    with pytest.raises(ValidationError):
        Settings.model_validate({"connection_method": "LocalAP", campo: valor})


def test_f005_padroes_de_dispositivo_da_spec() -> None:
    settings = Settings(_env_file=None, connection_method=ConnectionMethod.local_ap)

    assert settings.max_volume == 10
    assert settings.max_brightness == 10
    assert settings.led_max_duration_s == 60


def test_f004_padroes_de_estado_da_spec() -> None:
    settings = Settings(_env_file=None, connection_method=ConnectionMethod.local_ap)
    unlimited = Settings(
        _env_file=None, connection_method=ConnectionMethod.local_ap, state_max_hz=0
    )

    assert settings.state_max_clients == 4
    assert settings.state_max_hz == 10
    assert unlimited.state_max_hz == 0
