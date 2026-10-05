"""Testes de `MoveController`."""

import asyncio
from collections.abc import AsyncIterator

import pytest

from app.robot.channel import SportChannel
from app.robot.commands import MoveCommand, MoveLimits
from app.robot.link import RobotLink
from app.robot.movement import MoveController
from app.robot.unitree import SPORT_CMD
from tests.fakes import FakeConnectionFactory, FakePubSub

LIMITS = MoveLimits(max_vx=1.0, max_vy=1.0, max_vyaw=2.0, max_duration_s=10.0)


def _move(vx: float = 0.2, duration_s: float = 5.0) -> MoveCommand:
    return MoveCommand(vx=vx, vy=0.0, vyaw=0.0, duration_s=duration_s, limits=LIMITS)


@pytest.fixture
async def controller(factory: FakeConnectionFactory) -> AsyncIterator[MoveController]:
    link = RobotLink(factory)
    await link.connect()
    instance = MoveController(SportChannel(link, request_timeout_s=0.1), rate_hz=50.0)
    yield instance
    await instance.cancel()


async def test_start_dispara_move_imediatamente(
    controller: MoveController, pub_sub: FakePubSub
) -> None:
    await controller.start(_move(vx=0.3))

    assert pub_sub.api_ids == [SPORT_CMD["Move"]]
    assert pub_sub.parameter_of(0) == {"x": 0.3, "y": 0.0, "z": 0.0}
    assert controller.is_running is True


async def test_reenvia_e_para_no_fim_da_janela(
    controller: MoveController, pub_sub: FakePubSub
) -> None:
    # 50Hz durante 0.2s: o disparo imediato mais ~10 reenvios, e um StopMove.
    await controller.start(_move(duration_s=0.2))
    await asyncio.sleep(0.5)

    ids = pub_sub.api_ids
    assert ids[-1] == SPORT_CMD["StopMove"]
    assert ids.count(SPORT_CMD["Move"]) > 3, f"esperava reenvio contínuo, veio {ids}"
    assert controller.is_running is False


async def test_novo_movimento_cancela_o_anterior(
    controller: MoveController, pub_sub: FakePubSub
) -> None:
    await controller.start(_move(vx=0.2))
    await controller.start(_move(vx=0.4))
    enviados = len(pub_sub.sent)
    await asyncio.sleep(0.1)

    reenviados = pub_sub.fire_and_forget[enviados:]
    assert reenviados, "o novo movimento deveria estar reenviando"
    for msg in reenviados:
        assert '"x": 0.4' in msg["data"]["parameter"]


async def test_cancel_interrompe_sem_enviar_stopmove(
    controller: MoveController, pub_sub: FakePubSub
) -> None:
    await controller.start(_move())

    await controller.cancel()
    enviados = len(pub_sub.sent)
    await asyncio.sleep(0.1)

    assert controller.is_running is False
    assert len(pub_sub.sent) == enviados
    assert SPORT_CMD["StopMove"] not in pub_sub.api_ids


async def test_cancel_sem_movimento_e_inofensivo(controller: MoveController) -> None:
    await controller.cancel()

    assert controller.is_running is False


async def test_queda_de_conexao_encerra_o_loop_sem_stopmove(
    controller: MoveController, factory: FakeConnectionFactory, pub_sub: FakePubSub
) -> None:
    await controller.start(_move())

    factory.connection.isConnected = False
    await asyncio.sleep(0.1)
    enviados = len(pub_sub.sent)
    await asyncio.sleep(0.1)

    assert controller.is_running is False
    assert len(pub_sub.sent) == enviados


async def test_falha_inesperada_no_loop_e_registrada_e_encerra(
    controller: MoveController, pub_sub: FakePubSub, caplog: pytest.LogCaptureFixture
) -> None:
    await controller.start(_move())

    def quebra(*_: object, **__: object) -> None:
        raise RuntimeError("boom")

    pub_sub.publish_without_callback = quebra  # type: ignore[method-assign]
    await asyncio.sleep(0.1)

    assert controller.is_running is False
    assert "Falha no loop de movimento" in caplog.text
