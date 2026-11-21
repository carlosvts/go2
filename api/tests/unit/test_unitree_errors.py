"""F-004 A3: erros do data channel com a classe real `WebRTCDataChannel`.

A conexão é falsa (sem rede nem aiortc), mas o data channel, o gancho em
`datachannel` e o `handle_response` são os da lib 2.2.0.
"""

import asyncio
from collections.abc import AsyncIterator
from typing import Any

import pytest
from unitree_webrtc_connect.webrtc_datachannel import WebRTCDataChannel

from app.config import Settings
from app.robot.service import Go2Robot
from app.robot.unitree import VideoHookedConnection
from tests.fakes import FakePeerConnection


class _StubChannel:
    """O `RTCDataChannel` do aiortc só no que a lib usa sem rede."""

    readyState = "open"  # noqa: N815 - nome ditado pelo aiortc

    def on(self, event: str) -> Any:
        def register(handler: Any) -> Any:
            return handler

        return register

    def send(self, message: object) -> None:
        """Nada sai."""


class _StubPeer(FakePeerConnection):
    def createDataChannel(self, label: str) -> _StubChannel:  # noqa: N802
        return _StubChannel()


class RealChannelConnection(VideoHookedConnection):
    """Conexão da api com data channel real e sem rede.

    O `connect()` faz o que a lib faz em `init_webrtc`: cria o data channel
    (passando pelo gancho) e, antes de retornar, o robô manda `on_connect`.
    """

    def __init__(self, on_connect: list[dict[str, Any]] | None = None) -> None:
        # Sem `super().__init__`: nada de descoberta nem token.
        self.isConnected = False
        self.pc = _StubPeer()
        self.on_connect = on_connect or []

    async def connect(self) -> None:
        self.datachannel = WebRTCDataChannel(self, self.pc)
        self.datachannel.data_channel_opened = True
        for message in self.on_connect:
            await self.datachannel.handle_response(message)
        self.isConnected = True
        self.pc.connectionState = "connected"

    async def disconnect(self) -> None:
        self.isConnected = False
        self.pc.emit_state("closed")


class _Factory:
    def __init__(self, *plans: list[dict[str, Any]]) -> None:
        self._plans = list(plans)
        self.connections: list[RealChannelConnection] = []

    def __call__(self) -> RealChannelConnection:
        plan = self._plans.pop(0) if self._plans else []
        connection = RealChannelConnection(plan)
        self.connections.append(connection)
        return connection


def _item(source: int, code: int, ts: float = 1_700_000_000) -> list[Any]:
    return [ts, source, code]


async def _send(connection: RealChannelConnection, msg_type: str, data: Any) -> None:
    await connection.datachannel.handle_response({"type": msg_type, "data": data})


def _pairs(errors: list[dict[str, Any]] | None) -> list[tuple[int, int]] | None:
    if errors is None:
        return None
    return [(e["source"], e["code"]) for e in errors]


@pytest.fixture(autouse=True)
def _quiet_lib(capsys: pytest.CaptureFixture[str]) -> None:
    """A lib imprime cada erro com `print`; o capsys só engole a saída."""


async def _robot(settings: Settings, factory: _Factory) -> Go2Robot:
    robot = Go2Robot.from_settings(settings, factory)
    await robot.connect()
    return robot


@pytest.fixture
async def connected(
    settings: Settings,
) -> AsyncIterator[tuple[Go2Robot, _Factory]]:
    factory = _Factory()
    robot = await _robot(settings, factory)
    yield robot, factory
    await robot.disconnect()


# ─── (a) ───────────────────────────────────────────────────────────────────


async def test_a3a_fotografia_durante_o_connect_aparece_no_status(
    settings: Settings,
) -> None:
    factory = _Factory([{"type": "errors", "data": [_item(300, 16)]}])

    robot = await _robot(settings, factory)

    errors = robot.status().errors
    assert _pairs(errors) == [(300, 16)]
    await robot.disconnect()


# ─── (b) ───────────────────────────────────────────────────────────────────


async def test_a3b_add_acrescenta_sem_duplicar_e_rm_remove(
    connected: tuple[Go2Robot, _Factory],
) -> None:
    robot, factory = connected
    connection = factory.connections[-1]

    await _send(connection, "add_error", _item(300, 16))
    await _send(connection, "add_error", _item(300, 16, ts=1_700_000_100))
    await _send(connection, "add_error", _item(100, 1))
    assert _pairs(robot.status().errors) == [(300, 16), (100, 1)]

    await _send(connection, "rm_error", _item(300, 16))
    assert _pairs(robot.status().errors) == [(100, 1)]

    await _send(connection, "rm_error", _item(600, 4))
    assert _pairs(robot.status().errors) == [(100, 1)]

    await _send(connection, "rm_error", _item(100, 1))
    assert robot.status().errors == []


async def test_a3b_dados_em_lista_de_itens(
    connected: tuple[Go2Robot, _Factory],
) -> None:
    robot, factory = connected
    connection = factory.connections[-1]

    await _send(connection, "add_error", [_item(300, 16), _item(300, 4)])
    await _send(connection, "errors", [_item(200, 1)])

    assert _pairs(robot.status().errors) == [(200, 1)]


async def test_a3b_fotografia_vazia_da_lista_vazia(
    connected: tuple[Go2Robot, _Factory],
) -> None:
    robot, factory = connected

    await _send(factory.connections[-1], "errors", [])

    assert robot.status().errors == []


# ─── (c) ───────────────────────────────────────────────────────────────────


async def test_a3c_textos_e_hex_do_erro(
    connected: tuple[Go2Robot, _Factory],
) -> None:
    robot, factory = connected

    await _send(factory.connections[-1], "add_error", _item(300, 16, ts=1234))

    (error,) = robot.status().errors or []
    assert error["code_hex"] == "10"
    assert error["code_text"] == "Winding overheating"
    assert error["source_text"] == "Motor malfunction"
    assert error["robot_ts"] == 1234
    assert isinstance(error["seen_at"], float)
    assert set(error) == {
        "source",
        "source_text",
        "code",
        "code_hex",
        "code_text",
        "robot_ts",
        "seen_at",
    }


async def test_a3c_codigo_e_origem_sem_texto_usam_o_fallback(
    connected: tuple[Go2Robot, _Factory],
) -> None:
    robot, factory = connected

    await _send(factory.connections[-1], "errors", [_item(300, 3), _item(999, 255)])

    first, second = robot.status().errors or []
    assert (first["code_hex"], first["code_text"]) == ("3", "300-3")
    assert (second["source_text"], second["code_text"]) == ("999", "999-FF")


# ─── (d) ───────────────────────────────────────────────────────────────────


async def test_a3d_null_antes_da_primeira_mensagem_e_depois_da_queda(
    connected: tuple[Go2Robot, _Factory],
) -> None:
    robot, factory = connected
    assert robot.status().errors is None

    await _send(factory.connections[-1], "errors", [_item(300, 16)])
    assert robot.status().errors is not None

    factory.connections[-1].pc.emit_state("failed")
    assert robot.status().errors is None


# ─── (e) ───────────────────────────────────────────────────────────────────


async def test_a3e_depois_da_reconexao_so_o_canal_novo_conta(
    connected: tuple[Go2Robot, _Factory],
) -> None:
    robot, factory = connected
    old = factory.connections[-1]
    await _send(old, "errors", [_item(300, 16)])

    await robot.disconnect()
    await robot.connect()
    new = factory.connections[-1]
    assert new is not old
    assert robot.status().errors is None

    await _send(old, "add_error", _item(100, 1))
    assert robot.status().errors is None

    await _send(new, "add_error", _item(200, 2))
    assert _pairs(robot.status().errors) == [(200, 2)]


async def test_a3e_tentativa_que_falha_nao_deixa_erros(settings: Settings) -> None:
    class _FailingAfterErrors(RealChannelConnection):
        async def connect(self) -> None:
            await super().connect()
            msg = "validação falhou"
            raise OSError(msg)

    robot = Go2Robot.from_settings(
        settings,
        lambda: _FailingAfterErrors([{"type": "errors", "data": [_item(300, 16)]}]),
    )

    with pytest.raises(OSError, match="validação"):
        await robot.connect()

    assert robot.status().errors is None


# ─── (f) ───────────────────────────────────────────────────────────────────


async def test_a3f_excecao_da_api_nao_chega_a_lib(
    caplog: pytest.LogCaptureFixture,
) -> None:
    connection = RealChannelConnection()

    def explode(channel: object, message: dict[str, Any]) -> None:
        msg = "bug da api"
        raise RuntimeError(msg)

    connection.datachannel_message_listener = explode
    await connection.connect()

    await asyncio.wait_for(_send(connection, "add_error", _item(300, 16)), 1.0)

    assert "bug da api" in caplog.text


async def test_gancho_nao_atrapalha_as_outras_mensagens() -> None:
    connection = RealChannelConnection()
    received: list[dict[str, Any]] = []
    connection.datachannel_message_listener = lambda _ch, msg: received.append(msg)
    await connection.connect()

    await connection.datachannel.handle_response({"type": "heartbeat", "data": {}})
    await _send(connection, "rm_error", _item(300, 16))

    assert [m["type"] for m in received] == ["rm_error"]
