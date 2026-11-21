"""Refcount, ativação, teto, filas, estados e codificação do `/ws/video` (F-003)."""

import asyncio
import json
import math
import threading
from collections.abc import AsyncIterator, Callable
from typing import Any

import numpy as np
import pytest

from app.robot import video as video_module
from app.robot.connection import ConnectionState
from app.robot.link import RobotLink
from app.robot.streams import FrameClient, TrafficSaving
from app.robot.video import (
    HEADER_LEN,
    VIDEO_HEADER,
    VideoClient,
    VideoStream,
    encode_frame,
)
from tests.fakes import FakeConnectionFactory, FakeDataChannel, FakeVideoTrack
from tests.video_frames import (
    RED_SQUARE,
    BrokenFrame,
    SpyFrame,
    decode_jpeg,
    sample_image,
    video_frame,
)

TIMEOUT_S = 0.2


class Clock:
    """Relógio monotônico controlado pelo teste."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def track(factory: FakeConnectionFactory) -> FakeVideoTrack:
    instance = FakeVideoTrack()
    factory.connection.video_track = instance
    return instance


@pytest.fixture
def datachannel(factory: FakeConnectionFactory) -> FakeDataChannel:
    return factory.connection.datachannel


@pytest.fixture
def link(factory: FakeConnectionFactory) -> RobotLink:
    return RobotLink(factory)


def _stream(
    link: RobotLink,
    clock: Clock,
    *,
    max_clients: int = 2,
    client_queue: int = 1,
    encode_queue: int = 1,
    max_fps: float = 0.0,
    stall_s: float = 3.0,
    traffic: TrafficSaving | None = None,
    encoder: Callable[..., bytes] = encode_frame,
) -> VideoStream:
    return VideoStream(
        link,
        traffic=traffic or TrafficSaving(TIMEOUT_S),
        max_clients=max_clients,
        client_queue=client_queue,
        encode_queue=encode_queue,
        max_fps=max_fps,
        jpeg_quality=80,
        stall_s=stall_s,
        metrics_interval_s=None,
        stall_check_s=None,
        monotonic=clock,
        encoder=encoder,
    )


@pytest.fixture
async def stream(
    link: RobotLink, clock: Clock, track: FakeVideoTrack
) -> AsyncIterator[VideoStream]:
    instance = _stream(link, clock)
    instance.start()
    await link.connect()
    yield instance
    await instance.stop()


async def _next(client: FrameClient) -> Any:
    return await asyncio.wait_for(client.next(), 2.0)


async def _frames(client: FrameClient, count: int) -> list[bytes]:
    frames: list[bytes] = []
    while len(frames) < count:
        message = await _next(client)
        if message.kind == "bytes":
            frames.append(message.data)
    return frames


def _seq(frame: bytes) -> int:
    return int(VIDEO_HEADER.unpack_from(frame, 0)[3])


def _texts(client: FrameClient) -> list[dict[str, Any]]:
    return [json.loads(text) for text in client.pending_texts()]


def _video_states(client: FrameClient) -> list[str]:
    return [t["data"]["state"] for t in _texts(client) if t["topic"] == "video"]


async def _drain(track: FakeVideoTrack, stream: VideoStream) -> None:
    """Espera a api ler tudo da track e o worker esvaziar a fila."""
    for _ in range(200):
        if track.pending() == 0 and stream.pending_encode_count() == 0:
            await asyncio.sleep(0.005)
            if track.pending() == 0 and stream.pending_encode_count() == 0:
                return
        await asyncio.sleep(0.002)
    msg = "a api não drenou a track"
    raise AssertionError(msg)


async def _active(stream: VideoStream) -> VideoClient:
    client = stream.add_client()
    assert client is not None
    await stream.wait_idle()
    return client


# ─── A1: formato do frame (função de codificação) ──────────────────────────


def test_a1_frame_v1_com_jpeg_fiel_a_imagem() -> None:
    image = sample_image(1280, 720)
    frame = encode_frame(video_frame(image, time_s=2.5), 7, 1763380000.5, 80)

    fields = VIDEO_HEADER.unpack_from(frame, 0)
    version, flags, header_len, seq, ts, width, height, jpeg_len, media_time = fields
    assert (version, flags, header_len, seq) == (1, 0, 32, 7)
    assert ts == 1763380000.5
    assert (width, height) == (1280, 720)
    assert jpeg_len == len(frame) - HEADER_LEN
    assert media_time == pytest.approx(2.5)

    rgb = decode_jpeg(frame[HEADER_LEN:])
    assert rgb.shape == (720, 1280, 3)
    mse = float(np.mean((rgb.astype(np.float64) - image.astype(np.float64)) ** 2))
    assert 10 * math.log10(255**2 / mse) >= 30.0
    y0, y1, x0, x1 = RED_SQUARE
    r, g, b = (int(v) for v in rgb[(y0 + y1) // 2, (x0 + x1) // 2])
    assert r >= 200
    assert g <= 60
    assert b <= 60


def test_a1_media_time_nan_sem_tempo_no_quadro() -> None:
    frame = encode_frame(video_frame(time_s=None), 0, 1.0, 80)
    assert math.isnan(VIDEO_HEADER.unpack_from(frame, 0)[8])


# ─── A2: conversão e JPEG fora do event loop ───────────────────────────────


async def test_a2_conversao_e_jpeg_fora_do_loop(
    stream: VideoStream, track: FakeVideoTrack, monkeypatch: pytest.MonkeyPatch
) -> None:
    loop_thread = threading.get_ident()
    convert_threads: list[int] = []
    encode_threads: list[int] = []
    original = video_module._encoder

    def spy(*args: Any, **kwargs: Any) -> Any:
        encode_threads.append(threading.get_ident())
        return original(*args, **kwargs)

    monkeypatch.setattr(video_module, "_encoder", spy)
    client = await _active(stream)
    for _ in range(3):
        track.put(SpyFrame(video_frame(), convert_threads))
        await _frames(client, 1)

    assert len(convert_threads) == 3
    assert len(encode_threads) == 3
    assert loop_thread not in convert_threads + encode_threads
    assert len(set(convert_threads + encode_threads)) == 1


# ─── A3: track capturada a cada conexão, um leitor só ──────────────────────


async def test_a3_le_a_track_de_cada_conexao_com_um_leitor_so(
    link: RobotLink, clock: Clock, factory: FakeConnectionFactory
) -> None:
    stream = _stream(link, clock)
    stream.start()
    tracks = [FakeVideoTrack() for _ in range(4)]
    try:
        client = stream.add_client()
        assert client is not None
        for current in tracks:
            factory.connection.video_track = current
            await link.disconnect()
            await link.connect()
            await stream.wait_idle()
        assert stream.reader_count() == 1

        tracks[0].put(video_frame())
        tracks[-1].put(video_frame())
        await _drain(tracks[-1], stream)
        assert tracks[-1].received == 1
        assert tracks[0].received == 0
        assert len(await _frames(client, 1)) == 1
    finally:
        await stream.stop()


# ─── A4: refcount da câmera ────────────────────────────────────────────────


async def test_a4_refcount_liga_uma_vez_e_desliga_quando_todos_saem(
    stream: VideoStream, datachannel: FakeDataChannel, track: FakeVideoTrack
) -> None:
    first = await _active(stream)
    second = await _active(stream)
    assert datachannel.switch_video_calls == [True]

    stream.remove_client(first)
    await stream.wait_idle()
    assert datachannel.switch_video_calls == [True]
    stream.remove_client(second)
    await stream.wait_idle()
    assert datachannel.switch_video_calls == [True, False]

    track.put(video_frame())
    await _drain(track, stream)
    assert stream.admitted_total() == 0
    assert stream.encoded_total() == 0


async def test_a4_quadro_no_worker_quando_o_ultimo_sai_nao_e_enviado(
    link: RobotLink, clock: Clock, track: FakeVideoTrack
) -> None:
    gate = threading.Event()

    def held_encoder(*args: Any) -> bytes:
        gate.wait(2.0)
        return encode_frame(*args)

    stream = _stream(link, clock, encoder=held_encoder)
    stream.start()
    await link.connect()
    try:
        first = await _active(stream)
        track.put(video_frame())
        for _ in range(100):
            if stream.pending_encode_count() == 0 and track.pending() == 0:
                break
            await asyncio.sleep(0.005)
        stream.remove_client(first)
        await stream.wait_idle()
        second = await _active(stream)
        gate.set()
        await asyncio.sleep(0.1)

        kinds = [m.kind for m in second.drain_messages()]
        assert "bytes" not in kinds
    finally:
        gate.set()
        await stream.stop()


# ─── A5/A6: conexão fora do ar e reconexão ─────────────────────────────────


async def test_a5_robo_desligado_espera_sem_ligar_a_camera(
    link: RobotLink, clock: Clock, factory: FakeConnectionFactory, track: FakeVideoTrack
) -> None:
    stream = _stream(link, clock)
    stream.start()
    try:
        client = stream.add_client()
        assert client is not None
        await stream.wait_idle()
        texts = _texts(client)
        assert texts[0]["data"] == {"state": "disconnected"}
        assert factory.connection.datachannel.switch_video_calls == []

        await link.connect()
        await stream.wait_idle()
        assert factory.connection.datachannel.switch_video_calls == [True]
        track.put(video_frame())
        assert len(await _frames(client, 1)) == 1
    finally:
        await stream.stop()


async def test_a6_reconexao_reativa_sem_o_cliente_reconectar(
    stream: VideoStream,
    link: RobotLink,
    factory: FakeConnectionFactory,
    datachannel: FakeDataChannel,
) -> None:
    client = await _active(stream)
    client.pending_texts()
    new_track = FakeVideoTrack()
    factory.connection.video_track = new_track

    await link.disconnect()
    link.state.update(ConnectionState.reconnecting, reason="retry")
    await link.connect()
    await stream.wait_idle()

    texts = _texts(client)
    states = [t["data"]["state"] for t in texts]
    assert states[:3] == ["disconnected", "reconnecting", "connected"]
    assert states[3:] == ["starting"]
    assert datachannel.switch_video_calls == [True, True]
    new_track.put(video_frame())
    await _drain(new_track, stream)
    assert _video_states(client) == ["streaming"]
    assert len(await _frames(client, 1)) == 1


# ─── A7: teto de taxa ──────────────────────────────────────────────────────


async def test_a7_teto_de_taxa_admite_no_maximo_f_por_segundo(
    link: RobotLink, clock: Clock, track: FakeVideoTrack
) -> None:
    fps = 5.0
    stream = _stream(link, clock, max_fps=fps, client_queue=64)
    stream.start()
    await link.connect()
    try:
        client = await _active(stream)
        admitted_per_window: list[int] = []
        for _window in range(3):
            before = stream.admitted_total()
            for _ in range(int(3 * fps)):
                track.put(video_frame())
                await _drain(track, stream)
                clock.advance(1.0 / (3 * fps))
            admitted_per_window.append(stream.admitted_total() - before)
        assert all(n <= fps for n in admitted_per_window)
        assert stream.read_total() == 3 * int(3 * fps)

        seqs = [_seq(f) for f in await _frames(client, stream.admitted_total())]
        assert seqs == list(range(seqs[0], seqs[0] + len(seqs)))
    finally:
        await stream.stop()


async def test_a7_sem_teto_admite_todo_quadro(
    stream: VideoStream, track: FakeVideoTrack
) -> None:
    await _active(stream)
    for _ in range(5):
        track.put(video_frame())
        await _drain(track, stream)
    assert stream.admitted_total() == 5


# ─── A8: cliente lento ─────────────────────────────────────────────────────


async def test_a8_cliente_lento_recebe_o_mais_recente(
    stream: VideoStream, track: FakeVideoTrack
) -> None:
    fast = await _active(stream)
    slow = await _active(stream)
    fast.pending_texts()
    received: list[int] = []
    fast_topics: list[str] = []
    for index in range(4):
        track.put(video_frame())
        while True:
            message = await _next(fast)
            if isinstance(message.data, bytes):
                received.append(_seq(message.data))
                break
            fast_topics.append(json.loads(message.data)["topic"])
        if index == 1:
            stream.on_connection({"state": "connected", "reason": "teste"})

    assert received == sorted(received)
    assert len(received) == 4
    assert slow.pending_frame_count() == 1
    slow_topics = [t["topic"] for t in _texts(slow)]
    slow_frames = await _frames(slow, 1)
    assert _seq(slow_frames[0]) == received[-1]
    assert "connection" in fast_topics
    assert slow_topics.count("connection") == 2


# ─── A9: fila do codificador limitada ──────────────────────────────────────


async def test_a9_codificador_lento_descarta_o_mais_antigo(
    link: RobotLink, clock: Clock, track: FakeVideoTrack
) -> None:
    def slow_encoder(*args: Any) -> bytes:
        threading.Event().wait(0.05)
        return encode_frame(*args)

    stream = _stream(link, clock, encoder=slow_encoder, client_queue=64)
    stream.start()
    await link.connect()
    try:
        client = await _active(stream)
        max_pending = 0
        for _ in range(12):
            track.put(video_frame())
            await asyncio.sleep(0.005)
            max_pending = max(max_pending, stream.pending_encode_count())
        await _drain(track, stream)
        await asyncio.sleep(0.1)

        assert max_pending <= 1
        frames = [m.data for m in client.drain_messages() if isinstance(m.data, bytes)]
        seqs = [_seq(f) for f in frames]
        assert seqs == sorted(seqs)
        assert len(seqs) < 12
        assert stream.metrics_totals()["dropped_encode_queue"] == 12 - len(seqs)
    finally:
        await stream.stop()


# ─── A10: dreno sem clientes ───────────────────────────────────────────────


async def test_a10_sem_clientes_drena_a_track_sem_codificar(
    stream: VideoStream, track: FakeVideoTrack
) -> None:
    max_pending = 0
    for _ in range(20):
        track.put(video_frame())
        await asyncio.sleep(0.002)
        max_pending = max(max_pending, track.pending())

    await _drain(track, stream)
    assert max_pending <= 1
    assert stream.admitted_total() == 0
    assert stream.encoded_total() == 0
    assert stream.emit_metrics()["read"] == 20


# ─── A11: limite de clientes ───────────────────────────────────────────────


async def test_a11_limite_de_clientes(link: RobotLink, clock: Clock) -> None:
    stream = _stream(link, clock, max_clients=2)
    assert stream.add_client() is not None
    assert stream.add_client() is not None
    assert stream.add_client() is None
    zero = _stream(link, clock, max_clients=0)
    assert zero.add_client() is None
    await stream.stop()


# ─── A12: independente do LiDAR e do /status ───────────────────────────────


async def test_a12_video_nao_mexe_no_lidar(
    stream: VideoStream, factory: FakeConnectionFactory
) -> None:
    await _active(stream)
    assert factory.pub_sub.subscribe_calls == []
    assert factory.pub_sub.unsubscribed == []


# ─── A13: estados `video` ──────────────────────────────────────────────────


async def test_a13a_starting_e_depois_streaming(
    stream: VideoStream, track: FakeVideoTrack
) -> None:
    client = await _active(stream)
    assert _video_states(client) == ["starting"]
    track.put(video_frame())
    await _drain(track, stream)
    assert _video_states(client) == ["streaming"]
    assert len(await _frames(client, 1)) == 1


async def test_a13b_stalled_sem_quadro_e_volta_a_streaming(
    stream: VideoStream, track: FakeVideoTrack, clock: Clock
) -> None:
    client = await _active(stream)
    track.put(video_frame())
    await _frames(client, 1)
    client.pending_texts()

    clock.advance(2.9)
    stream.check_stall()
    assert _video_states(client) == []
    clock.advance(0.2)
    stream.check_stall()
    assert _video_states(client) == ["stalled"]

    track.put(video_frame())
    await _drain(track, stream)
    assert _video_states(client) == ["streaming"]


async def test_a13b_stalled_quando_a_track_nunca_chega(
    link: RobotLink, clock: Clock
) -> None:
    stream = _stream(link, clock)
    stream.start()
    await link.connect()
    try:
        client = await _active(stream)
        clock.advance(3.1)
        stream.check_stall()
        assert _video_states(client) == ["starting", "stalled"]
        assert stream.reader_count() == 0
    finally:
        await stream.stop()


async def test_a13b_stalled_quando_a_track_termina(
    stream: VideoStream, track: FakeVideoTrack, clock: Clock
) -> None:
    client = await _active(stream)
    track.end()
    for _ in range(100):
        if stream.reader_count() == 0:
            break
        await asyncio.sleep(0.005)
    assert stream.reader_count() == 0
    clock.advance(3.1)
    stream.check_stall()
    assert _video_states(client) == ["starting", "stalled"]


async def test_a13c_quadro_lido_antes_do_true_nao_vira_streaming(
    stream: VideoStream, track: FakeVideoTrack
) -> None:
    track.put(video_frame())
    await _drain(track, stream)
    client = await _active(stream)
    await asyncio.sleep(0.05)
    assert _video_states(client) == ["starting"]
    assert stream.admitted_total() == 0


async def test_a13d_websocket_nao_fecha_nos_estados(
    stream: VideoStream, track: FakeVideoTrack, clock: Clock
) -> None:
    client = await _active(stream)
    clock.advance(5)
    stream.check_stall()
    track.put(video_frame())
    await _frames(client, 1)
    assert not client.is_closed


async def test_a13e_excecao_no_switch_fecha_com_1011_sem_nova_tentativa(
    stream: VideoStream, datachannel: FakeDataChannel
) -> None:
    datachannel.switch_video_error = RuntimeError("canal fechado")
    client = await _active(stream)

    messages = client.drain_messages()
    closes = [m for m in messages if m.kind == "close"]
    assert [(m.code, m.reason) for m in closes] == [(1011, "video_unavailable")]
    await asyncio.sleep(0.05)
    assert datachannel.switch_video_calls == [True]
    assert datachannel.traffic_saving_calls == [True, False]


async def test_a13f_quadro_corrompido_e_pulado(
    stream: VideoStream, track: FakeVideoTrack
) -> None:
    client = await _active(stream)
    track.put(BrokenFrame())
    await _drain(track, stream)
    await asyncio.sleep(0.05)
    track.put(video_frame())
    frames = await _frames(client, 1)

    assert _seq(frames[0]) == 1
    assert stream.encode_errors_total() == 1
