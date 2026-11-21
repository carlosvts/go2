"""A6 (F-007): par `RTCPeerConnection` real do aiortc em loopback, no processo.

O ofertante imita a lib (`addTransceiver("audio", direction="sendrecv")`); o
outro lado faz o papel do robô e lê os quadros recebidos. Prova que a track
persistente segue enviando depois do fim de um arquivo — não prova nada do
robô (codec aceito, alto-falante).
"""

import asyncio
import contextlib
import time
from typing import Any

import numpy as np
import pytest
from aiortc import MediaStreamTrack, RTCPeerConnection

from app.robot.link import RobotLink
from app.robot.speaker import Speaker
from app.robot.unitree import attach_audio_track
from tests.audio_files import make_wav
from tests.fakes import FakeConnection

LOUD = 1000  # RMS acima do qual o quadro recebido "tem som" (seno de amplitude 0,5)


class LoopbackConnection(FakeConnection):
    """Conexão falsa cuja track vai para um `RTCPeerConnection` real."""

    def __init__(self, peer: RTCPeerConnection) -> None:
        super().__init__()
        self.real_pc = peer

    def attach_audio_track(self, track: Any) -> None:
        super().attach_audio_track(track)
        attach_audio_track(self.real_pc, track)


async def _negotiate(offerer: RTCPeerConnection, answerer: RTCPeerConnection) -> None:
    await offerer.setLocalDescription(await offerer.createOffer())
    await answerer.setRemoteDescription(offerer.localDescription)
    await answerer.setLocalDescription(await answerer.createAnswer())
    await offerer.setRemoteDescription(answerer.localDescription)


async def _collect(track: MediaStreamTrack, log: list[tuple[float, float]]) -> None:
    with contextlib.suppress(Exception):
        while True:
            frame: Any = await track.recv()
            pcm = frame.to_ndarray().astype(np.float64)
            log.append((time.monotonic(), float(np.sqrt(np.mean(pcm**2)))))


async def _wait_idle(speaker: Speaker, timeout_s: float) -> None:
    deadline = time.monotonic() + timeout_s
    while speaker.snapshot.state != "idle":
        assert time.monotonic() < deadline, "o arquivo não acabou a tempo"
        await asyncio.sleep(0.02)


def _loud_between(log: list[tuple[float, float]], start: float, end: float) -> int:
    return sum(1 for at, rms in log if start <= at <= end and rms > LOUD)


@pytest.mark.slow
async def test_two_files_in_a_row_reach_the_other_peer() -> None:
    robot_side = RTCPeerConnection()
    lib_side = RTCPeerConnection()
    lib_side.addTransceiver("audio", direction="sendrecv")
    received: list[tuple[float, float]] = []
    collectors: list[asyncio.Task[None]] = []

    @robot_side.on("track")
    def on_track(track: MediaStreamTrack) -> None:
        if track.kind == "audio":
            collectors.append(asyncio.create_task(_collect(track, received)))

    try:
        await _negotiate(lib_side, robot_side)
        deadline = time.monotonic() + 10
        while lib_side.connectionState != "connected":
            assert time.monotonic() < deadline, lib_side.connectionState
            await asyncio.sleep(0.05)

        link = RobotLink(lambda: LoopbackConnection(lib_side))
        await link.connect()
        speaker = Speaker(link)

        first_start = time.monotonic()
        await speaker.play(make_wav(seconds=0.6), "um.wav")
        await _wait_idle(speaker, 5)
        first_end = time.monotonic()
        await asyncio.sleep(0.4)  # silêncio entre os dois

        second_start = time.monotonic()
        await speaker.play(make_wav(seconds=0.6, freq=660), "dois.wav")
        await _wait_idle(speaker, 5)
        await asyncio.sleep(0.5)  # jitter buffer do receptor
        second_end = time.monotonic()

        assert _loud_between(received, first_start, first_end + 0.4) >= 10
        assert _loud_between(received, second_start, second_end) >= 10
        # Entre os dois, chegou silêncio (a track não parou).
        quiet = [rms for at, rms in received if first_end + 0.25 < at < second_start]
        assert quiet
        assert min(quiet) < LOUD
    finally:
        for task in collectors:
            task.cancel()
        await lib_side.close()
        await robot_side.close()
