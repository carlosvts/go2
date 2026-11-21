"""Rotas `/speaker/*` (F-007), com a conexão falsa."""

import threading
import time
from collections.abc import Iterator
from typing import TYPE_CHECKING, Any

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.robot import speaker as speaker_module
from app.robot.speaker import AudioClip, SpeakerTrack
from tests.audio_files import make_mp3, make_wav
from tests.fakes import FakeConnectionFactory

if TYPE_CHECKING:
    from pathlib import Path


def _play(client: TestClient, data: bytes, name: str = "a.wav") -> Any:
    return client.post("/speaker/play", files={"file": (name, data)})


@pytest.mark.parametrize(
    ("name", "make"), [("a.wav", make_wav), ("b.mp3", make_mp3)], ids=["wav", "mp3"]
)
def test_play_returns_202_and_get_shows_playing(
    client: TestClient, factory: FakeConnectionFactory, name: str, make: Any
) -> None:
    """A1 (WAV) e A2 (MP3)."""
    response = _play(client, make(seconds=0.5), name)
    assert response.status_code == 202
    body = response.json()
    assert set(body) == {"playback_id", "name", "duration_s"}
    assert body["name"] == name
    assert body["duration_s"] == pytest.approx(0.5, abs=0.1)
    assert isinstance(factory.connection.audio_tracks[0], SpeakerTrack)
    status = client.get("/speaker").json()
    assert status["state"] == "playing"
    assert status["playback_id"] == body["playback_id"]
    assert status["name"] == name
    assert status["duration_s"] == body["duration_s"]
    assert status["started_at"] is not None


def test_get_speaker_matches_listener_dict(client: TestClient) -> None:
    """O gancho do `/ws/state` recebe o mesmo dict do `GET /speaker`."""
    events: list[dict[str, Any]] = []
    client.app.state.robot.speaker.subscribe(events.append)  # type: ignore[attr-defined]
    _play(client, make_wav(seconds=1))
    assert events == [client.get("/speaker").json()]


def test_idle_shape(client: TestClient) -> None:
    assert client.get("/speaker").json() == {
        "state": "idle",
        "playback_id": None,
        "name": None,
        "started_at": None,
        "duration_s": None,
    }


def test_stop_is_202_even_when_idle(client: TestClient) -> None:
    """A4."""
    assert client.post("/speaker/stop").status_code == 202
    assert client.post("/speaker/stop").json() == {"state": "idle"}
    _play(client, make_wav(seconds=1))
    assert client.post("/speaker/stop").json() == {"state": "idle"}
    assert client.get("/speaker").json()["state"] == "idle"


def test_too_large_is_413(settings: Settings, factory: FakeConnectionFactory) -> None:
    """A8: acima de `GO2_AUDIO_MAX_UPLOAD_MB` → 413, sem tocar na track."""
    small = settings.model_copy(update={"audio_max_upload_mb": 0.01})
    with TestClient(create_app(small, connection_factory=factory)) as client:
        response = _play(client, make_wav(seconds=1))  # ~88 KB > ~10 KB
        assert response.status_code == 413
        assert factory.connection.audio_tracks == []
        assert _play(client, make_wav(seconds=0.05)).status_code == 202


def test_too_large_without_content_length_is_413(
    settings: Settings, factory: FakeConnectionFactory
) -> None:
    """A8: o limite vale na leitura em streaming, não só pelo cabeçalho."""
    small = settings.model_copy(update={"audio_max_upload_mb": 0.01})
    boundary = "xyz"
    body = (
        (
            f'--{boundary}\r\nContent-Disposition: form-data; name="file"; '
            'filename="a.wav"\r\n\r\n'
        ).encode()
        + make_wav(seconds=1)
        + f"\r\n--{boundary}--\r\n".encode()
    )

    def chunks() -> Iterator[bytes]:
        for start in range(0, len(body), 4096):
            yield body[start : start + 4096]

    with TestClient(create_app(small, connection_factory=factory)) as client:
        response = client.post(
            "/speaker/play",
            content=chunks(),
            headers={"content-type": f"multipart/form-data; boundary={boundary}"},
        )
        assert response.status_code == 413
        assert factory.connection.audio_tracks == []


@pytest.mark.parametrize(
    "data", [b"plain text" * 20, b"OggS" + b"\x00" * 100], ids=["text", "ogg"]
)
def test_invalid_format_is_415(
    client: TestClient, factory: FakeConnectionFactory, data: bytes
) -> None:
    """A8."""
    assert _play(client, data, "x.bin").status_code == 415
    assert factory.connection.audio_tracks == []


def test_offline_is_503(offline_client: TestClient) -> None:
    """A8."""
    assert _play(offline_client, make_wav()).status_code == 503


def test_missing_file_field_is_422(client: TestClient) -> None:
    response = client.post("/speaker/play", files={"other": ("a.wav", make_wav())})
    assert response.status_code == 422
    assert client.post("/speaker/play", content=b"x").status_code == 422


def test_capabilities_do_not_list_speaker(client: TestClient) -> None:
    assert "speaker" not in client.get("/capabilities").text


@pytest.fixture(scope="module")
def max_size_mp3(tmp_path_factory: pytest.TempPathFactory) -> bytes:
    """MP3 logo abaixo de 5 MiB (o padrão de `GO2_AUDIO_MAX_UPLOAD_MB`)."""
    path: Path = tmp_path_factory.mktemp("audio") / "max.mp3"
    data = make_mp3(seconds=128, bit_rate=320_000)
    path.write_bytes(data)
    return data


@pytest.mark.slow
def test_stop_responds_fast_during_max_size_decode(
    client: TestClient, max_size_mp3: bytes, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A9: decodificação fora do loop; `POST /commands/stop` em < 100 ms."""
    assert len(max_size_mp3) > 4.5 * 1024 * 1024
    started = threading.Event()
    finished = threading.Event()
    threads: list[int] = []
    real = speaker_module.decode_audio

    def spy(data: bytes, name: str) -> AudioClip:
        threads.append(threading.get_ident())
        started.set()
        try:
            return real(data, name)
        finally:
            finished.set()

    monkeypatch.setattr(speaker_module, "decode_audio", spy)
    results: list[int] = []
    player = threading.Thread(
        target=lambda: results.append(
            _play(client, max_size_mp3, "max.mp3").status_code
        )
    )
    player.start()
    assert started.wait(10)
    begin = time.perf_counter()
    response = client.post("/commands/stop")
    elapsed = time.perf_counter() - begin
    decoding_after_stop = not finished.is_set()
    player.join(30)
    assert response.status_code == 202
    assert elapsed < 0.1
    assert decoding_after_stop
    assert results == [202]
    loop_thread = client.portal.call(threading.get_ident)  # type: ignore[union-attr]
    assert threads[0] != loop_thread
