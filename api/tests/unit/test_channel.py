"""Testes de `SportChannel` e `ObstacleAvoidChannel`."""

import pytest

from app.exceptions import RobotTimeoutError, RobotUnavailableError
from app.robot.channel import ObstacleAvoidChannel, SportChannel
from app.robot.link import RobotLink
from app.robot.unitree import (
    DATA_CHANNEL_TYPE,
    OBSTACLES_AVOID_API,
    RTC_TOPIC,
    SPORT_CMD,
)
from tests.fakes import FakeConnectionFactory, FakePubSub


@pytest.fixture
async def link(factory: FakeConnectionFactory) -> RobotLink:
    instance = RobotLink(factory)
    await instance.connect()
    return instance


@pytest.fixture
async def channel(link: RobotLink) -> SportChannel:
    return SportChannel(link, request_timeout_s=0.1)


async def test_send_publica_no_topico_esportivo_como_request(
    channel: SportChannel, pub_sub: FakePubSub
) -> None:
    channel.send("StandUp")

    enviado = pub_sub.sent[0]
    assert enviado["topic"] == RTC_TOPIC["SPORT_MOD"]
    assert enviado["type"] == DATA_CHANNEL_TYPE["REQUEST"]
    assert pub_sub.api_ids == [SPORT_CMD["StandUp"]]
    assert pub_sub.parameter_of(0) is None


async def test_send_serializa_o_parametro(
    channel: SportChannel, pub_sub: FakePubSub
) -> None:
    channel.send("SpeedLevel", {"data": 1})

    assert pub_sub.parameter_of(0) == {"data": 1}


async def test_send_sem_conexao_levanta_unavailable(
    factory: FakeConnectionFactory,
) -> None:
    channel = SportChannel(RobotLink(factory), request_timeout_s=0.1)

    with pytest.raises(RobotUnavailableError):
        channel.send("StandUp")


async def test_request_devolve_a_resposta(
    channel: SportChannel, pub_sub: FakePubSub
) -> None:
    pub_sub.response = {"data": {"data": 2}}

    resposta = await channel.request("GetSpeedLevel")

    assert resposta == {"data": {"data": 2}}
    assert pub_sub.sent[0]["options"] == {"api_id": SPORT_CMD["GetSpeedLevel"]}


async def test_request_inclui_o_parametro_quando_ha(
    channel: SportChannel, pub_sub: FakePubSub
) -> None:
    pub_sub.response = {}

    await channel.request("GetSpeedLevel", {"x": 1})

    assert pub_sub.sent[0]["options"]["parameter"] == {"x": 1}


async def test_request_estoura_timeout(
    channel: SportChannel, pub_sub: FakePubSub
) -> None:
    pub_sub.hang_on_request = True

    with pytest.raises(RobotTimeoutError, match="não respondeu"):
        await channel.request("GetSpeedLevel")


async def test_request_sem_conexao_levanta_unavailable(
    factory: FakeConnectionFactory,
) -> None:
    channel = SportChannel(RobotLink(factory), request_timeout_s=0.1)

    with pytest.raises(RobotUnavailableError):
        await channel.request("GetSpeedLevel")


async def test_canal_do_desvio_usa_o_proprio_topico_e_a_propria_tabela(
    link: RobotLink, pub_sub: FakePubSub
) -> None:
    channel = ObstacleAvoidChannel(link, request_timeout_s=0.1)
    pub_sub.response = {"data": {"data": {"enable": True}}}

    channel.send("SWITCH_SET", {"enable": True})
    await channel.request("SWITCH_GET")

    assert [msg["topic"] for msg in pub_sub.sent] == [RTC_TOPIC["OBSTACLES_AVOID"]] * 2
    assert pub_sub.api_ids == [OBSTACLES_AVOID_API["SWITCH_SET"]]
    assert pub_sub.sent[1]["options"] == {"api_id": OBSTACLES_AVOID_API["SWITCH_GET"]}
