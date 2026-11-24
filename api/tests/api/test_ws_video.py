"""Rota `/ws/video` com a app real e o robô falso (F-003)."""

import json
import time
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from starlette.testclient import WebSocketTestSession
from starlette.websockets import WebSocketDisconnect

from app.config import Settings
from app.main import create_app
from app.robot.video import HEADER_LEN, VIDEO_HEADER
from tests.fakes import FakeConnectionFactory, FakeVideoTrack
from tests.video_frames import video_frame


@pytest.fixture
def track(factory: FakeConnectionFactory) -> FakeVideoTrack:
    instance = FakeVideoTrack()
    factory.connection.video_track = instance
    return instance


@pytest.fixture
def zero_clients(
    factory: FakeConnectionFactory, settings: Settings
) -> Iterator[TestClient]:
    app = create_app(
        settings.model_copy(update={"video_max_clients": 0}),
        connection_factory=factory,
    )
    with TestClient(app) as test_client:
        yield test_client


def _until_bytes(ws: WebSocketTestSession) -> tuple[list[dict[str, Any]], bytes]:
    texts: list[dict[str, Any]] = []
    while True:
        message = ws.receive()
        if message.get("bytes") is not None:
            return texts, message["bytes"]
        texts.append(json.loads(message["text"]))


def _wait(condition: Any, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while not condition():
        assert time.monotonic() < deadline, "condição não aconteceu"
        time.sleep(0.01)


def test_conexao_starting_streaming_e_frame(
    track: FakeVideoTrack, client: TestClient, factory: FakeConnectionFactory
) -> None:
    # `track` antes de `client`: a lib entrega a track durante o `connect()`.
    with client.websocket_connect("/ws/video") as ws:
        first = json.loads(ws.receive_text())
        _wait(lambda: factory.connection.datachannel.switch_video_calls == [True])
        assert client.portal is not None
        client.portal.call(track.put, video_frame(width=1280, height=720))
        texts, frame = _until_bytes(ws)

    assert first["topic"] == "connection"
    assert first["data"] == {"state": "connected"}
    states = [t["data"]["state"] for t in texts if t["topic"] == "video"]
    assert states == ["starting", "streaming"]
    version, _, header_len, seq, _, width, height, jpeg_len, _ = (
        VIDEO_HEADER.unpack_from(frame, 0)
    )
    assert (version, header_len, seq, width, height) == (1, 32, 0, 1280, 720)
    assert jpeg_len == len(frame) - HEADER_LEN
    assert frame[HEADER_LEN : HEADER_LEN + 2] == b"\xff\xd8"


def test_robo_fora_do_ar_mantem_o_cliente_esperando(offline_client: TestClient) -> None:
    with offline_client.websocket_connect("/ws/video") as ws:
        assert json.loads(ws.receive_text())["data"]["state"] == "disconnected"


def test_a11_terceiro_cliente_leva_1013_com_o_limite_padrao(
    client: TestClient,
) -> None:
    with (
        client.websocket_connect("/ws/video") as first,
        client.websocket_connect("/ws/video") as second,
    ):
        first.receive_text()
        second.receive_text()
        with (
            client.websocket_connect("/ws/video") as third,
            pytest.raises(WebSocketDisconnect) as closed,
        ):
            third.receive_text()

    assert closed.value.code == 1013


def test_a11_limite_zero_desliga_a_rota(zero_clients: TestClient) -> None:
    with (
        zero_clients.websocket_connect("/ws/video") as ws,
        pytest.raises(WebSocketDisconnect) as closed,
    ):
        ws.receive_text()

    assert closed.value.code == 1013


def test_cliente_que_sai_desliga_a_camera(
    client: TestClient, factory: FakeConnectionFactory
) -> None:
    datachannel = factory.connection.datachannel
    with client.websocket_connect("/ws/video") as ws:
        ws.receive_text()
        _wait(lambda: datachannel.switch_video_calls == [True])

    _wait(lambda: datachannel.switch_video_calls == [True, False])
    _wait(lambda: datachannel.traffic_saving_calls == [True, False])


def test_a12_status_segue_respondendo_com_video_ativo(
    client: TestClient, factory: FakeConnectionFactory
) -> None:
    with client.websocket_connect("/ws/video") as ws:
        ws.receive_text()
        _wait(lambda: factory.connection.datachannel.switch_video_calls == [True])
        response = client.get("/status")

    assert response.status_code == 200
    assert response.json()["connected"] is True
