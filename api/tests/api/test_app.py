"""Testes da app factory, do lifespan e da injeção de dependências."""

from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import Settings
from app.dependencies import get_robot
from app.main import create_app
from app.robot.commands import SportCommand
from app.robot.service import Go2Robot
from tests.fakes import FakeConnectionFactory


def test_lifespan_conecta_na_subida_e_desconecta_na_descida(
    settings: Settings, factory: FakeConnectionFactory
) -> None:
    app = create_app(settings, connection_factory=factory)

    with TestClient(app):
        assert factory.calls == 1
        assert factory.connection.isConnected is True

    assert factory.connection.disconnected is True


def test_com_connect_on_startup_falso_nao_cria_conexao(
    unconnected_client: TestClient, factory: FakeConnectionFactory
) -> None:
    assert factory.calls == 0


def test_falha_ao_conectar_nao_impede_a_api_de_subir(
    offline_client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    assert offline_client.get("/status").status_code == 200


def test_importar_o_modulo_nao_le_configuracao() -> None:
    """Não há `app` global: nada acontece (nem exige `.env`) ao importar."""
    from app import main  # noqa: PLC0415 - o import é o objeto do teste

    assert not hasattr(main, "app")


def test_create_app_le_o_ambiente_quando_nao_recebe_settings(
    monkeypatch: pytest.MonkeyPatch, factory: FakeConnectionFactory
) -> None:
    monkeypatch.setenv("GO2_ROBOT_IP", "192.168.1.50")
    monkeypatch.setenv("GO2_CONNECT_ON_STARTUP", "false")

    app = create_app(connection_factory=factory)

    assert app.state.settings.robot_ip == "192.168.1.50"


def test_create_app_sem_configuracao_valida_falha_ao_construir() -> None:
    with pytest.raises(ValueError, match="GO2_ROBOT_IP"):
        create_app()


def test_documenta_os_endpoints_no_openapi(settings: Settings) -> None:
    schema = create_app(settings).openapi()

    assert set(schema["paths"]) == {
        "/status",
        "/commands/posture",
        "/commands/gesture",
        "/commands/move",
        "/commands/stop",
        "/commands/speed",
    }


class _RecordingRobot:
    """Robô de mentira que só registra as chamadas dos routers."""

    def __init__(self) -> None:
        self.executed: list[SportCommand] = []

    async def execute(self, command: SportCommand) -> None:
        self.executed.append(command)


@pytest.fixture
def stub_app(settings: Settings) -> Iterator[tuple[FastAPI, _RecordingRobot]]:
    """App com `get_robot` sobrescrito: testa o router isolado do domínio."""
    app = create_app(settings.model_copy(update={"connect_on_startup": False}))
    robot = _RecordingRobot()
    app.dependency_overrides[get_robot] = lambda: robot
    yield app, robot
    app.dependency_overrides.clear()


def test_router_entrega_ao_robo_o_enum_ja_validado(
    stub_app: tuple[FastAPI, _RecordingRobot],
) -> None:
    app, robot = stub_app

    with TestClient(app) as client:
        resposta = client.post("/commands/posture", json={"cmd": "balance_stand"})

    assert resposta.status_code == 202
    assert [c.sport_cmd for c in robot.executed] == ["BalanceStand"]


def test_go2robot_e_o_tipo_injetado_em_producao(
    settings: Settings, factory: FakeConnectionFactory
) -> None:
    app = create_app(settings, connection_factory=factory)

    with TestClient(app):
        assert isinstance(app.state.robot, Go2Robot)
