"""Alto-falante (F-007): decodificação, track persistente e ordem play/stop."""

import asyncio
import threading
import time
from typing import TYPE_CHECKING, Any

import av
import numpy as np
import pytest

from app.exceptions import (
    PayloadTooLargeError,
    RobotUnavailableError,
    UnsupportedAudioError,
)
from app.robot.link import RobotLink
from app.robot.speaker import (
    FRAME_SAMPLES,
    SAMPLE_RATE,
    AudioClip,
    Speaker,
    SpeakerTrack,
    decode_audio,
)
from tests.audio_files import make_mp3, make_wav
from tests.fakes import FakeConnection, FakeConnectionFactory

if TYPE_CHECKING:
    from collections.abc import Callable

# ─── Decodificação ──────────────────────────────────────────────────────────


def test_decode_wav_resamples_to_48k_stereo() -> None:
    clip = decode_audio(make_wav(seconds=0.5, rate=44100, channels=1), "a.wav")
    assert clip.name == "a.wav"
    assert clip.pcm.dtype == np.int16
    assert clip.pcm.ndim == 2
    assert clip.pcm.shape[1] == 2
    assert clip.duration_s == pytest.approx(0.5, abs=0.01)
    assert clip.duration_s == clip.pcm.shape[0] / SAMPLE_RATE
    assert np.abs(clip.pcm).max() > 10_000


def test_decode_mp3() -> None:
    clip = decode_audio(make_mp3(seconds=0.5), "b.mp3")
    assert clip.pcm.shape[1] == 2
    # O MP3 acrescenta preenchimento do codec: a duração só é aproximada.
    assert clip.duration_s == pytest.approx(0.5, abs=0.1)
    assert np.abs(clip.pcm).max() > 10_000


@pytest.mark.parametrize(
    "data",
    [
        b"",
        b"not audio at all" * 100,
        b"OggS" + b"\x00" * 200,
        b"RIFF\x00\x00\x00\x00WAVEgarbage",
        b"ID3\x03\x00\x00\x00\x00\x00\x00" + b"\x00" * 100,
    ],
)
def test_decode_rejects_unknown_or_broken(data: bytes) -> None:
    with pytest.raises(UnsupportedAudioError):
        decode_audio(data, "x")


# ─── Track persistente ──────────────────────────────────────────────────────


def _pcm(frame: Any) -> np.ndarray:
    assert frame.sample_rate == SAMPLE_RATE
    assert frame.format.name == "s16"
    assert frame.layout.name == "stereo"
    assert frame.samples == FRAME_SAMPLES
    array: np.ndarray = frame.to_ndarray()
    return array.reshape(-1, 2)


async def test_idle_track_delivers_silence_at_real_time_pace() -> None:
    """A3: silêncio a cada 20 ms (±5 ms em média por 1 s, relógio real)."""
    track = SpeakerTrack()
    first = await track.recv()
    start = time.monotonic()
    pts = [first.pts]
    for _ in range(50):
        frame = await track.recv()
        assert not _pcm(frame).any()
        pts.append(frame.pts)
    mean_interval = (time.monotonic() - start) / 50
    assert 0.015 <= mean_interval <= 0.025
    assert pts == [i * FRAME_SAMPLES for i in range(51)]
    assert str(first.time_base) == f"1/{SAMPLE_RATE}"


async def test_track_plays_clip_frames_then_returns_to_silence() -> None:
    """A1/A3: entrega o PCM em quadros de 20 ms e volta ao silêncio."""
    clip = decode_audio(make_wav(seconds=0.07), "a.wav")
    ended: list[int] = []
    track = SpeakerTrack()
    track.play(clip.pcm, lambda: ended.append(1))
    received = [_pcm(await track.recv()) for _ in range(4)]
    joined = np.concatenate(received)
    count = clip.pcm.shape[0]
    np.testing.assert_array_equal(joined[:count], clip.pcm)
    assert not joined[count:].any()  # último quadro completado com zeros
    assert ended == [1]
    assert not track.playing
    assert not _pcm(await track.recv()).any()


async def test_track_silence_cuts_without_end_callback() -> None:
    clip = decode_audio(make_wav(seconds=0.5), "a.wav")
    ended: list[int] = []
    track = SpeakerTrack()
    track.play(clip.pcm, lambda: ended.append(1))
    assert _pcm(await track.recv()).any()
    track.silence()
    assert not _pcm(await track.recv()).any()
    assert ended == []


async def test_track_never_ends() -> None:
    track = SpeakerTrack()
    track.play(decode_audio(make_wav(seconds=0.02), "a").pcm, lambda: None)
    for _ in range(3):
        await track.recv()
    assert track.readyState == "live"


# ─── Speaker: estado, ordem, conexão ────────────────────────────────────────


class SequenceFactory:
    """Uma conexão nova a cada `connect()`, como a fábrica real."""

    def __init__(self) -> None:
        self.connections: list[FakeConnection] = []

    def __call__(self) -> FakeConnection:
        connection = FakeConnection()
        self.connections.append(connection)
        return connection


class GatedDecoder:
    """Decodificador real segurado por um evento por chamada."""

    def __init__(self) -> None:
        self.gates: list[threading.Event] = []
        self.started = threading.Semaphore(0)
        self.threads: list[int] = []

    def __call__(self, data: bytes, name: str) -> AudioClip:
        gate = threading.Event()
        self.gates.append(gate)
        self.threads.append(threading.get_ident())
        self.started.release()
        assert gate.wait(5)
        return decode_audio(data, name)

    async def wait_started(self) -> None:
        assert await asyncio.to_thread(self.started.acquire, True, 5)


@pytest.fixture
async def link(factory: FakeConnectionFactory) -> RobotLink:
    instance = RobotLink(factory)
    await instance.connect()
    return instance


def _speaker(link: RobotLink, **kwargs: Any) -> tuple[Speaker, list[dict[str, Any]]]:
    speaker = Speaker(link, **kwargs)
    events: list[dict[str, Any]] = []
    speaker.subscribe(events.append)
    return speaker, events


async def test_play_attaches_track_once_and_reports_playing(
    link: RobotLink, factory: FakeConnectionFactory
) -> None:
    """A1: `play` põe a track persistente e o estado vai a `playing`."""
    speaker, events = _speaker(link)
    playback = await speaker.play(make_wav(seconds=0.5), "a.wav")
    assert playback.name == "a.wav"
    assert playback.duration_s == pytest.approx(0.5, abs=0.01)
    attached = factory.connection.audio_tracks
    assert len(attached) == 1
    assert isinstance(attached[0], SpeakerTrack)
    snapshot = speaker.snapshot.as_dict()
    assert snapshot["state"] == "playing"
    assert snapshot["playback_id"] == playback.playback_id
    assert snapshot["name"] == "a.wav"
    assert snapshot["duration_s"] == playback.duration_s
    assert snapshot["started_at"].endswith("Z")
    assert events == [snapshot]
    await speaker.play(make_wav(seconds=0.5), "b.wav")
    assert len(factory.connection.audio_tracks) == 1  # mesma track


async def test_end_of_clip_goes_idle_and_notifies(
    link: RobotLink, factory: FakeConnectionFactory
) -> None:
    """A3: ao acabar o arquivo, `idle` e aviso aos ouvintes (gancho do /ws/state)."""
    speaker, events = _speaker(link)
    await speaker.play(make_wav(seconds=0.03), "a.wav")
    track = factory.connection.audio_tracks[0]
    await track.recv()
    await track.recv()
    assert speaker.snapshot.state == "idle"
    assert [event["state"] for event in events] == ["playing", "idle"]
    assert events[-1] == speaker.snapshot.as_dict()
    assert events[-1]["playback_id"] is None


async def test_second_play_replaces_first(
    link: RobotLink, factory: FakeConnectionFactory
) -> None:
    """A4: o segundo `play` troca o som na mesma track."""
    speaker, _ = _speaker(link)
    await speaker.play(make_wav(seconds=1, freq=440), "a.wav")
    second = await speaker.play(make_wav(seconds=1, freq=880), "b.wav")
    expected = decode_audio(make_wav(seconds=1, freq=880), "b.wav").pcm
    track = factory.connection.audio_tracks[0]
    received = _pcm(await track.recv())
    np.testing.assert_array_equal(received, expected[:FRAME_SAMPLES])
    assert speaker.snapshot.playback_id == second.playback_id


async def test_stop_silences_and_goes_idle(
    link: RobotLink, factory: FakeConnectionFactory
) -> None:
    """A4: `stop` volta ao silêncio e ao `idle`; sem nada tocando, também ok."""
    speaker, events = _speaker(link)
    idle = await speaker.stop()
    assert idle.state == "idle"
    assert events == []  # nada mudou
    await speaker.play(make_wav(seconds=1), "a.wav")
    stopped = await speaker.stop()
    assert stopped.state == "idle"
    track = factory.connection.audio_tracks[0]
    assert not _pcm(await track.recv()).any()
    assert [event["state"] for event in events] == ["playing", "idle"]


async def test_stop_during_decode_cancels_play(
    link: RobotLink, factory: FakeConnectionFactory
) -> None:
    """A5: `stop` durante a decodificação faz o `play` terminar sem tocar."""
    decoder = GatedDecoder()
    speaker, events = _speaker(link, decoder=decoder)
    task = asyncio.create_task(speaker.play(make_wav(), "a.wav"))
    await decoder.wait_started()
    await speaker.stop()
    decoder.gates[0].set()
    await task
    assert speaker.snapshot.state == "idle"
    assert factory.connection.audio_tracks == []
    assert events == []
    assert decoder.threads[0] != threading.get_ident()  # A9: fora do loop


async def test_last_accepted_play_wins(
    link: RobotLink, factory: FakeConnectionFactory
) -> None:
    """A5: entre dois `play` segurados, toca o último aceito."""
    decoder = GatedDecoder()
    speaker, _ = _speaker(link, decoder=decoder)
    first = asyncio.create_task(speaker.play(make_wav(freq=440), "first.wav"))
    await decoder.wait_started()
    second = asyncio.create_task(speaker.play(make_wav(freq=880), "second.wav"))
    await decoder.wait_started()
    decoder.gates[1].set()
    await second
    decoder.gates[0].set()
    await first
    assert speaker.snapshot.name == "second.wav"
    # Ordem inversa de liberação: o primeiro termina depois e não toca.
    decoder2 = GatedDecoder()
    speaker2, _ = _speaker(link, decoder=decoder2)
    a = asyncio.create_task(speaker2.play(make_wav(), "a.wav"))
    await decoder2.wait_started()
    b = asyncio.create_task(speaker2.play(make_wav(), "b.wav"))
    await decoder2.wait_started()
    decoder2.gates[0].set()
    await a
    assert speaker2.snapshot.state == "idle"
    decoder2.gates[1].set()
    await b
    assert speaker2.snapshot.name == "b.wav"


async def test_connection_drop_goes_idle_and_next_play_attaches_new_track() -> None:
    """A7: queda → `idle`; nada toca na reconexão; o próximo `play` reinstala."""
    factory = SequenceFactory()
    link = RobotLink(factory)
    await link.connect()
    speaker, events = _speaker(link)
    await speaker.play(make_wav(seconds=2), "a.wav")
    old_track = factory.connections[0].audio_tracks[0]
    factory.connections[0].pc.emit_state("failed")
    assert speaker.snapshot.state == "idle"
    assert not _pcm(await old_track.recv()).any()
    await link.disconnect()
    await link.connect()
    assert speaker.snapshot.state == "idle"
    assert factory.connections[1].audio_tracks == []
    await speaker.play(make_wav(seconds=2), "b.wav")
    new_tracks = factory.connections[1].audio_tracks
    assert len(new_tracks) == 1
    assert new_tracks[0] is not old_track
    assert [event["state"] for event in events] == ["playing", "idle", "playing"]


async def test_connection_change_during_decode_is_503() -> None:
    factory = SequenceFactory()
    link = RobotLink(factory)
    await link.connect()
    decoder = GatedDecoder()
    speaker, _ = _speaker(link, decoder=decoder)
    task = asyncio.create_task(speaker.play(make_wav(), "a.wav"))
    await decoder.wait_started()
    await link.disconnect()
    await link.connect()
    decoder.gates[0].set()
    with pytest.raises(RobotUnavailableError):
        await task
    assert factory.connections[1].audio_tracks == []


async def test_play_without_connection_is_unavailable(
    factory: FakeConnectionFactory,
) -> None:
    """A8: sem conexão, 503 e a track não muda."""
    speaker, _ = _speaker(RobotLink(factory))
    with pytest.raises(RobotUnavailableError):
        await speaker.play(make_wav(), "a.wav")
    assert factory.connection.audio_tracks == []


async def test_unsupported_audio_keeps_current_playback(
    link: RobotLink, factory: FakeConnectionFactory
) -> None:
    """A8: formato inválido → erro, e o que tocava continua."""
    speaker, _ = _speaker(link)
    playing = await speaker.play(make_wav(seconds=1), "a.wav")
    with pytest.raises(UnsupportedAudioError):
        await speaker.play(b"nope" * 50, "x.ogg")
    assert speaker.snapshot.playback_id == playing.playback_id
    assert len(factory.connection.audio_tracks) == 1


async def test_failing_listener_does_not_break_others(link: RobotLink) -> None:
    speaker = Speaker(link)
    seen: list[str] = []

    def broken(_: dict[str, Any]) -> None:
        raise RuntimeError

    recorder: Callable[[dict[str, Any]], None] = lambda e: seen.append(e["state"])  # noqa: E731
    speaker.subscribe(broken)
    speaker.subscribe(recorder)
    await speaker.play(make_wav(), "a.wav")
    assert seen == ["playing"]


def test_a14_decodificacao_para_no_teto_mesmo_sem_duracao_no_cabecalho(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A14: sem a duração no cabeçalho, a contagem de amostras para a leitura."""
    original_open = av.open

    def open_without_duration(*args: Any, **kwargs: Any) -> Any:
        container = original_open(*args, **kwargs)

        class _NoDuration:
            def __init__(self, inner: Any) -> None:
                self._inner = inner
                self.duration = None

            def __getattr__(self, attr: str) -> Any:
                return getattr(self._inner, attr)

            def __enter__(self) -> Any:
                self._inner.__enter__()
                return self

            def __exit__(self, *exc: Any) -> Any:
                return self._inner.__exit__(*exc)

        return _NoDuration(container)

    monkeypatch.setattr(av, "open", open_without_duration)
    with pytest.raises(PayloadTooLargeError):
        decode_audio(make_wav(seconds=3.0), "longo.wav", max_duration_s=1.0)
    clip = decode_audio(make_wav(seconds=0.5), "curto.wav", max_duration_s=1.0)
    assert clip.duration_s == pytest.approx(0.5, abs=0.05)
