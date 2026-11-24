"""Ligação entre o alto-falante (F-007 A3) e o `/ws/state` (F-004)."""

import json
from typing import Any

from app.config import Settings
from app.robot.service import Go2Robot
from app.robot.state_stream import StateClient
from tests.audio_files import make_wav
from tests.fakes import FakeConnectionFactory


def _topics(client: StateClient) -> list[dict[str, Any]]:
    return [json.loads(text) for text in client.drain()]


async def test_speaker_no_aceite_e_a_cada_mudanca(
    settings: Settings, factory: FakeConnectionFactory
) -> None:
    robot = Go2Robot.from_settings(settings, factory)
    await robot.connect()
    try:
        client = robot.state_stream.add_client()
        assert client is not None
        first = [t for t in _topics(client) if t["topic"] == "speaker"]
        assert [t["data"]["state"] for t in first] == ["idle"]

        await robot.speaker.play(make_wav(seconds=0.5), "a.wav")
        await robot.speaker.stop()

        states = [
            t["data"]["state"] for t in _topics(client) if t["topic"] == "speaker"
        ]
        assert states == ["playing", "idle"]
    finally:
        await robot.speaker.stop()
        await robot.disconnect()


async def test_audio_player_no_ws_state_e_silence_cala_o_alto_falante(
    settings: Settings, factory: FakeConnectionFactory
) -> None:
    robot = Go2Robot.from_settings(settings, factory)
    await robot.connect()
    try:
        factory.pub_sub.response = {
            "data": {"header": {"status": {"code": 0}}, "data": "{}"}
        }
        client = robot.state_stream.add_client()
        assert client is not None
        client.drain()

        factory.pub_sub.publish_state("rt/audiohub/player/state", {"state": "play"})
        players = [t for t in _topics(client) if t["topic"] == "audio_player"]
        assert [t["data"] for t in players] == [{"state": "play"}]

        await robot.speaker.play(make_wav(seconds=2), "a.wav")
        assert robot.speaker.snapshot.as_dict()["state"] == "playing"
        await robot.audio.silence()
        assert robot.speaker.snapshot.as_dict()["state"] == "idle"

        late = robot.state_stream.add_client()
        assert late is not None
        assert "audio_player" in [t["topic"] for t in _topics(late)]
    finally:
        await robot.speaker.stop()
        await robot.disconnect()
