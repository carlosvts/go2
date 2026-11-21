"""Testes da camada VUI (F-005): canal, comando de LED e leitura das respostas."""

import json

import pytest

from app.exceptions import InvalidCommandError, RobotRejectedError
from app.robot.channel import VUI_API, VuiChannel
from app.robot.device import LedColor, LedCommand, VuiResponse
from app.robot.link import RobotLink
from app.robot.unitree import RTC_TOPIC, VUI_COLOR
from tests.fakes import FakeConnectionFactory, FakePubSub


def _resposta(code: object = 0, data: object = "") -> dict[str, object]:
    return {"data": {"header": {"status": {"code": code}}, "data": data}}


def test_api_ids_do_exemplo_vui() -> None:
    assert VUI_API == {
        "SetVolume": 1003,
        "GetVolume": 1004,
        "SetBrightness": 1005,
        "GetBrightness": 1006,
        "SetLed": 1007,
    }


def test_cores_sao_as_da_lib() -> None:
    da_lib = {
        value
        for name, value in vars(VUI_COLOR).items()
        if not name.startswith("_") and isinstance(value, str)
    }
    assert {color.value for color in LedColor} == da_lib


async def test_canal_vui_publica_no_topico_vui_com_parameter_dict(
    factory: FakeConnectionFactory, pub_sub: FakePubSub
) -> None:
    link = RobotLink(factory)
    await link.connect()
    pub_sub.response = _resposta()

    await VuiChannel(link, request_timeout_s=0.1).request("SetVolume", {"volume": 2})

    assert pub_sub.sent[0]["topic"] == RTC_TOPIC["VUI"]
    assert pub_sub.sent[0]["options"] == {"api_id": 1003, "parameter": {"volume": 2}}


@pytest.mark.parametrize(
    ("duration_s", "flash", "esperado"),
    [
        (5, None, {"color": "red", "time": 5}),
        (5, 499, {"color": "red", "time": 5, "flash_cycle": 499}),
        (5, 5000, {"color": "red", "time": 5, "flash_cycle": 5000}),
        (60, None, {"color": "red", "time": 60}),
    ],
)
def test_led_command_monta_o_parameter(
    duration_s: int, flash: int | None, esperado: dict[str, object]
) -> None:
    comando = LedCommand(
        color=LedColor.red,
        duration_s=duration_s,
        flash_cycle_ms=flash,
        max_duration_s=60,
    )
    assert comando.parameter == esperado


@pytest.mark.parametrize(
    ("duration_s", "flash", "teto"),
    [(0, None, 60), (61, None, 60), (6, None, 5), (5, 498, 60), (5, 5001, 60)],
)
def test_led_command_fora_dos_limites_nao_existe(
    duration_s: int, flash: int | None, teto: int
) -> None:
    with pytest.raises(InvalidCommandError):
        LedCommand(
            color=LedColor.red,
            duration_s=duration_s,
            flash_cycle_ms=flash,
            max_duration_s=teto,
        )


def test_aceite_com_codigo_zero_passa() -> None:
    VuiResponse.ensure_accepted(_resposta(code=0))


@pytest.mark.parametrize(
    "resposta",
    [
        _resposta(code=1),
        _resposta(code="0"),
        _resposta(code=None),
        {"data": {"header": {"status": {}}}},
        {"data": {"header": {}}},
        {"data": {}},
        {"data": "x"},
        {},
        None,
    ],
)
def test_resposta_recusada_ou_sem_status_levanta_rejected(resposta: object) -> None:
    with pytest.raises(RobotRejectedError):
        VuiResponse.ensure_accepted(resposta)


def test_read_level_decodifica_data_data() -> None:
    resposta = _resposta(data=json.dumps({"volume": 9}))

    assert VuiResponse.read_level(resposta, "volume") == 9


@pytest.mark.parametrize(
    "data",
    [
        json.dumps({"outro": 1}),
        "{",
        "",
        None,
        json.dumps({"volume": 1.5}),
        json.dumps({"volume": False}),
        json.dumps("volume"),
    ],
)
def test_read_level_sem_o_campo_levanta_rejected(data: object) -> None:
    with pytest.raises(RobotRejectedError):
        VuiResponse.read_level(_resposta(data=data), "volume")
