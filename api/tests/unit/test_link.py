"""Testes de `RobotLink`."""

import pytest

from app.exceptions import RobotUnavailableError
from app.robot.connection import ConnectionState
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


async def test_falha_ao_conectar_fecha_a_conexao_pela_metade() -> None:
    """Sem isso cada tentativa de reconexão deixaria um peer aberto."""
    factory = FakeConnectionFactory(FakeConnection(connect_error=OSError("sem rede")))
    link = RobotLink(factory)

    with pytest.raises(OSError, match="sem rede"):
        await link.connect()

    assert factory.connection.disconnected is True


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


# ─── Estado publicado da conexão ───────────────────────────────────────────


@pytest.fixture
def received() -> list[dict[str, str]]:
    return []


@pytest.fixture
def link(factory: FakeConnectionFactory, received: list[dict[str, str]]) -> RobotLink:
    instance = RobotLink(factory)
    instance.state.subscribe(received.append)
    return instance


async def test_connect_publica_connected(
    link: RobotLink, received: list[dict[str, str]]
) -> None:
    await link.connect()

    assert received == [{"state": "connected", "reason": "connected"}]
    assert link.state.current.state is ConnectionState.connected


async def test_falha_ao_conectar_mantem_disconnected_sem_publicar(
    received: list[dict[str, str]],
) -> None:
    factory = FakeConnectionFactory(FakeConnection(connect_error=OSError("sem rede")))
    link = RobotLink(factory)
    link.state.subscribe(received.append)

    with pytest.raises(OSError, match="sem rede"):
        await link.connect()

    assert link.state.current.state is ConnectionState.disconnected
    assert received == []


async def test_failed_do_peer_publica_disconnected(
    link: RobotLink, factory: FakeConnectionFactory, received: list[dict[str, str]]
) -> None:
    await link.connect()

    factory.connection.pc.emit_state("failed")

    assert received[-1] == {"state": "disconnected", "reason": "failed"}
    assert link.state.current.state is ConnectionState.disconnected


async def test_eventos_iguais_seguidos_geram_uma_mensagem(
    link: RobotLink, factory: FakeConnectionFactory, received: list[dict[str, str]]
) -> None:
    await link.connect()

    factory.connection.pc.emit_state("failed")
    factory.connection.pc.emit_state("failed")

    assert received[1:] == [{"state": "disconnected", "reason": "failed"}]


async def test_peer_que_volta_publica_connected(
    link: RobotLink, factory: FakeConnectionFactory, received: list[dict[str, str]]
) -> None:
    await link.connect()

    factory.connection.pc.emit_state("disconnected")
    factory.connection.pc.emit_state("connected")

    assert [m["state"] for m in received] == ["connected", "disconnected", "connected"]


async def test_failed_nao_muda_is_connected(
    link: RobotLink, factory: FakeConnectionFactory
) -> None:
    """O estado publicado é informativo: quem decide o `503` é `is_connected`.

    A lib não zera `isConnected` em `failed`, então os dois podem divergir.
    """
    await link.connect()

    factory.connection.pc.emit_state("failed")

    assert link.state.current.state is ConnectionState.disconnected
    assert link.is_connected is True


async def test_ouvinte_da_lib_continua_registrado(
    link: RobotLink, factory: FakeConnectionFactory
) -> None:
    chamadas: list[str] = []
    factory.connection.pc.on("connectionstatechange", lambda: chamadas.append("lib"))

    await link.connect()
    factory.connection.pc.emit_state("failed")

    assert chamadas == ["lib"]
    assert len(factory.connection.pc.handlers["connectionstatechange"]) == 2


async def test_disconnect_publica_disconnected_uma_vez(
    link: RobotLink, received: list[dict[str, str]]
) -> None:
    await link.connect()

    await link.disconnect()

    assert received[1:] == [{"state": "disconnected", "reason": "closed"}]


async def test_disconnect_depois_de_queda_nao_republica(
    link: RobotLink, factory: FakeConnectionFactory, received: list[dict[str, str]]
) -> None:
    await link.connect()
    factory.connection.pc.emit_state("failed")

    await link.disconnect()

    assert [m["state"] for m in received] == ["connected", "disconnected"]


async def test_eventos_de_conexao_encerrada_sao_ignorados(
    link: RobotLink, factory: FakeConnectionFactory, received: list[dict[str, str]]
) -> None:
    await link.connect()
    await link.disconnect()

    factory.connection.pc.emit_state("connected")

    assert link.state.current.state is ConnectionState.disconnected
    assert len(received) == 2
