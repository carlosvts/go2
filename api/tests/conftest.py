"""Fixtures compartilhadas dos testes."""

import os
from collections.abc import AsyncIterator

import pytest

from app.config import ConnectionMethod, Settings
from app.robot.service import Go2Robot
from tests.fakes import FakeConnectionFactory, FakePubSub


@pytest.fixture(autouse=True)
def _isolated_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Impede que variáveis `GO2_*` do desenvolvedor vazem para os testes."""
    for key in list(os.environ):
        if key.startswith("GO2_"):
            monkeypatch.delenv(key)


@pytest.fixture
def settings() -> Settings:
    """Configuração válida, hermética (sem `.env`) e com reenvio rápido."""
    return Settings(
        _env_file=None,
        connection_method=ConnectionMethod.local_sta,
        robot_ip="192.168.1.50",
        connect_on_startup=True,
        move_rate_hz=50.0,
        move_max_duration_s=10.0,
        max_vx=1.0,
        max_vy=1.0,
        max_vyaw=2.0,
        request_timeout_s=0.2,
    )


@pytest.fixture
def factory() -> FakeConnectionFactory:
    """Fábrica de conexões falsas, com um robô \"ligado\"."""
    return FakeConnectionFactory()


@pytest.fixture
def pub_sub(factory: FakeConnectionFactory) -> FakePubSub:
    """Canal pub/sub da conexão falsa, para inspecionar o que foi enviado."""
    return factory.pub_sub


@pytest.fixture
async def robot(
    settings: Settings, factory: FakeConnectionFactory
) -> AsyncIterator[Go2Robot]:
    """`Go2Robot` conectado à conexão falsa."""
    instance = Go2Robot.from_settings(settings, factory)
    await instance.connect()
    yield instance
    await instance.disconnect()


@pytest.fixture
def offline_robot(settings: Settings, factory: FakeConnectionFactory) -> Go2Robot:
    """`Go2Robot` que nunca conectou — o robô desligado."""
    return Go2Robot.from_settings(settings, factory)
