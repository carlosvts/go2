"""Testes de `RobotLink`."""

import pytest

from app.exceptions import RobotUnavailableError
from app.robot.link import RobotLink
from tests.fakes import FakeConnection, FakeConnectionFactory


async def test_sem_conectar_nao_esta_conectado(factory: FakeConnectionFactory) -> None:
    link = RobotLink(factory)

    assert link.is_connected is False
    assert factory.calls == 0


async def test_connect_abre_a_conexao(factory: FakeConnectionFactory) -> None:
    link = RobotLink(factory)

    await link.connect()

    assert link.is_connected is True
    assert link.ensure_connected() is factory.pub_sub


async def test_falha_ao_conectar_nao_guarda_a_conexao() -> None:
    factory = FakeConnectionFactory(FakeConnection(connect_error=OSError("sem rede")))
    link = RobotLink(factory)

    with pytest.raises(OSError, match="sem rede"):
        await link.connect()

    assert link.is_connected is False
    with pytest.raises(RobotUnavailableError):
        _ = link.pub_sub


async def test_datachannel_fechado_conta_como_desconectado(
    factory: FakeConnectionFactory,
) -> None:
    link = RobotLink(factory)
    await link.connect()

    factory.connection.datachannel.data_channel_opened = False

    assert link.is_connected is False
    with pytest.raises(RobotUnavailableError):
        link.ensure_connected()


async def test_nao_reconecta_sozinho(factory: FakeConnectionFactory) -> None:
    """Queda de conexão não dispara reconexão silenciosa."""
    link = RobotLink(factory)
    await link.connect()

    factory.connection.isConnected = False

    with pytest.raises(RobotUnavailableError):
        link.ensure_connected()
    assert factory.calls == 1


async def test_disconnect_encerra_a_conexao(factory: FakeConnectionFactory) -> None:
    link = RobotLink(factory)
    await link.connect()

    await link.disconnect()

    assert factory.connection.disconnected is True
    assert link.is_connected is False


async def test_disconnect_sem_conexao_e_inofensivo(
    factory: FakeConnectionFactory,
) -> None:
    await RobotLink(factory).disconnect()

    assert factory.connection.disconnected is False


async def test_disconnect_ignora_falha_de_encerramento(
    factory: FakeConnectionFactory,
) -> None:
    async def falha() -> None:
        raise RuntimeError("já caiu")

    link = RobotLink(factory)
    await link.connect()
    factory.connection.disconnect = falha  # type: ignore[method-assign]

    await link.disconnect()

    assert link.is_connected is False
