"""Fixtures dos testes de endpoint: app real, conexão com o robô falsa."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.config import ConnectionMethod, Settings
from app.main import create_app
from tests.fakes import FakeConnection, FakeConnectionFactory


@pytest.fixture
def client(settings: Settings, factory: FakeConnectionFactory) -> Iterator[TestClient]:
    """Cliente com o robô \"ligado\": o lifespan conecta na conexão falsa."""
    with TestClient(create_app(settings, connection_factory=factory)) as test_client:
        yield test_client


@pytest.fixture
def offline_client(settings: Settings) -> Iterator[TestClient]:
    """Cliente com o robô \"desligado\": a conexão falha na subida da API."""
    factory = FakeConnectionFactory(FakeConnection(connect_error=OSError("sem robô")))
    with TestClient(create_app(settings, connection_factory=factory)) as test_client:
        yield test_client


@pytest.fixture
def unconnected_client(factory: FakeConnectionFactory) -> Iterator[TestClient]:
    """Cliente de uma API que sobe com `GO2_CONNECT_ON_STARTUP=false`."""
    settings = Settings(
        _env_file=None,
        connection_method=ConnectionMethod.local_ap,
        connect_on_startup=False,
    )
    with TestClient(create_app(settings, connection_factory=factory)) as test_client:
        yield test_client
