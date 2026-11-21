"""Ordem, taxa, filas e métricas do `/ws/state` (F-004 A4–A6, A8)."""

import itertools
import json
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import pytest

from app.robot.connection import ConnectionState
from app.robot.errors import ActiveErrors
from app.robot.link import RobotLink
from app.robot.state import StateCache
from app.robot.state_stream import StateClient, StateStream
from app.robot.unitree import RTC_TOPIC
from tests.fakes import FakeConnectionFactory, FakePubSub
from tests.state_payloads import low_state, multiple_state, sport_state


class Clock:
    def __init__(self, now: float) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@dataclass
class Rig:
    link: RobotLink
    cache: StateCache
    errors: ActiveErrors
    stream: StateStream
    pub_sub: FakePubSub
    wall: Clock
    mono: Clock

    def low(self, **overrides: Any) -> None:
        self.pub_sub.publish_state(RTC_TOPIC["LOW_STATE"], low_state(**overrides))

    def sport(self, **overrides: Any) -> None:
        self.pub_sub.publish_state(
            RTC_TOPIC["SPORT_MOD_STATE"], sport_state(**overrides)
        )

    def multi(self) -> None:
        self.pub_sub.publish_state(RTC_TOPIC["MULTIPLE_STATE"], multiple_state())

    def error(self, msg_type: str, data: Any) -> None:
        channel = self.link.datachannel
        self.errors.on_message(channel, {"type": msg_type, "data": data})


async def _rig(
    factory: FakeConnectionFactory, *, max_hz: float = 0.0, max_clients: int = 4
) -> Rig:
    wall, mono = Clock(1_763_380_000.0), Clock(1000.0)
    link = RobotLink(factory)
    cache = StateCache(clock=mono, wall_clock=wall)
    errors = ActiveErrors(wall_clock=wall)
    link.subscribe_datachannel_messages(errors.on_message)
    link.state.subscribe(errors.on_connection)
    stream = StateStream(
        link,
        cache,
        errors,
        max_clients=max_clients,
        max_hz=max_hz,
        metrics_interval_s=None,
        clock=wall,
        monotonic=mono,
    )
    stream.start()
    await link.connect()
    cache.attach(link.pub_sub)
    return Rig(link, cache, errors, stream, factory.pub_sub, wall, mono)


@pytest.fixture
async def rig(factory: FakeConnectionFactory) -> AsyncIterator[Rig]:
    instance = await _rig(factory)
    yield instance
    await instance.stream.stop()


def _frames(client: StateClient) -> list[dict[str, Any]]:
    return [json.loads(text) for text in client.drain()]


def _topics(client: StateClient) -> list[str]:
    return [frame["topic"] for frame in _frames(client)]


# ─── A4 ────────────────────────────────────────────────────────────────────


async def test_a4_ao_aceitar_connection_secoes_e_errors(rig: Rig) -> None:
    rig.low()
    low_ts = rig.wall.now
    rig.wall.advance(1.0)
    rig.sport()
    rig.wall.advance(1.0)
    rig.error("errors", [[1, 300, 16]])
    rig.wall.advance(5.0)

    client = rig.stream.add_client()
    assert client is not None
    frames = _frames(client)

    assert [f["topic"] for f in frames] == [
        "connection",
        "battery",
        "imu",
        "motion",
        "motors",
        "body_temperature_c",
        "errors",
    ]
    assert frames[0]["data"] == {"state": "connected"}
    assert frames[1]["ts"] == low_ts  # chegada original, não o aceite
    assert frames[1]["data"]["percent"] == 87
    assert frames[2]["ts"] == low_ts + 1.0
    assert [e["code"] for e in frames[-1]["data"]] == [16]


async def test_a4_errors_null_no_aceite_sem_mensagem(rig: Rig) -> None:
    client = rig.stream.add_client()
    assert client is not None

    frames = _frames(client)

    assert [f["topic"] for f in frames] == ["connection", "errors"]
    assert frames[1]["data"] is None


async def test_a4_um_frame_por_secao_a_cada_mensagem(rig: Rig) -> None:
    client = rig.stream.add_client()
    assert client is not None
    client.drain()

    rig.low()
    assert _topics(client) == ["battery", "motors", "body_temperature_c"]
    rig.sport()
    assert _topics(client) == ["imu", "motion"]
    rig.multi()
    assert _topics(client) == ["settings"]


async def test_a4_queda_e_volta(rig: Rig) -> None:
    client = rig.stream.add_client()
    assert client is not None
    client.drain()
    rig.error("errors", [[1, 300, 16]])
    client.drain()

    rig.link.state.update(ConnectionState.reconnecting, reason="retry")
    dropped = _frames(client)
    rig.link.state.update(ConnectionState.connected, reason="connected")
    back = _frames(client)
    rig.sport()

    assert [(f["topic"], f["data"]) for f in dropped] == [
        ("connection", {"state": "reconnecting"}),
        ("errors", None),
    ]
    assert [(f["topic"], f["data"]) for f in back] == [
        ("connection", {"state": "connected"}),
    ]
    assert _topics(client) == ["imu", "motion"]


async def test_a4_errors_a_cada_mudanca(rig: Rig) -> None:
    client = rig.stream.add_client()
    assert client is not None
    client.drain()

    rig.error("add_error", [1, 300, 16])
    rig.error("add_error", [2, 300, 16])  # repetido: não muda
    rig.error("rm_error", [3, 300, 16])

    frames = _frames(client)
    assert [len(f["data"]) for f in frames] == [1, 0]


async def test_json_montado_uma_vez_e_compartilhado(rig: Rig) -> None:
    first = rig.stream.add_client()
    second = rig.stream.add_client()
    assert first is not None
    assert second is not None
    first.drain()
    second.drain()

    rig.low()

    for a, b in zip(first.drain(), second.drain(), strict=True):
        assert a is b


# ─── A5 ────────────────────────────────────────────────────────────────────


async def test_a5_teto_por_topico_com_o_retido_saindo_no_fim_da_janela(
    factory: FakeConnectionFactory,
) -> None:
    hz = 10.0
    rig = await _rig(factory, max_hz=hz)
    client = rig.stream.add_client()
    assert client is not None
    client.drain()
    received: list[tuple[float, int]] = []

    def collect() -> None:
        for frame in _frames(client):
            if frame["topic"] == "battery":
                received.append((rig.mono.now, frame["data"]["percent"]))

    last = 0
    for i in range(int(5 * hz * 2)):  # 2 s a 5H
        last = i
        rig.low(bms_state={"soc": i})
        collect()
        rig.mono.advance(1 / (5 * hz))
    rig.mono.advance(1.0)  # o tópico parou; a janela fecha
    collect()

    times = [t for t, _ in received]
    gaps = [b - a for a, b in itertools.pairwise(times)]
    assert min(gaps) >= 1 / hz - 1e-9
    for start in times:
        assert sum(1 for t in times if start <= t < start + 1.0) <= hz
    assert received[-1][1] == last
    await rig.stream.stop()


async def test_a5_sem_teto_recebe_todos(rig: Rig) -> None:
    client = rig.stream.add_client()
    assert client is not None
    client.drain()

    count = 0
    for i in range(50):
        rig.low(bms_state={"soc": i})
        count += sum(1 for f in _frames(client) if f["topic"] == "battery")

    assert count == 50


async def test_a5_topicos_tem_janelas_independentes(
    factory: FakeConnectionFactory,
) -> None:
    rig = await _rig(factory, max_hz=10.0)
    client = rig.stream.add_client()
    assert client is not None
    client.drain()

    rig.low()
    rig.sport()

    assert _topics(client) == [
        "battery",
        "motors",
        "body_temperature_c",
        "imu",
        "motion",
    ]
    await rig.stream.stop()


async def test_a5_connection_e_errors_nao_tem_teto(
    factory: FakeConnectionFactory,
) -> None:
    rig = await _rig(factory, max_hz=1.0)
    client = rig.stream.add_client()
    assert client is not None
    client.drain()

    for i in range(10):
        rig.error("add_error", [i, 300, i])

    assert _topics(client) == ["errors"] * 10
    await rig.stream.stop()


# ─── A6 ────────────────────────────────────────────────────────────────────


async def test_a6_lento_fica_com_um_por_topico_e_nao_atrasa_o_outro(
    rig: Rig,
) -> None:
    slow = rig.stream.add_client()
    fast = rig.stream.add_client()
    assert slow is not None
    assert fast is not None
    slow.drain()
    fast.drain()

    fast_battery = 0
    for i in range(100):
        rig.low(bms_state={"soc": i})
        rig.sport()
        fast_battery += sum(1 for f in _frames(fast) if f["topic"] == "battery")
    rig.error("add_error", [1, 300, 16])
    rig.error("rm_error", [2, 300, 16])

    assert fast_battery == 100
    assert slow.pending_section_count() <= 5  # 5 seções alimentadas
    frames = _frames(slow)
    sections = [f for f in frames if f["topic"] != "errors"]
    assert len({f["topic"] for f in sections}) == len(sections)
    battery = next(f for f in sections if f["topic"] == "battery")
    assert battery["data"]["percent"] == 99
    errors = [f["data"] for f in frames if f["topic"] == "errors"]
    assert [[e["code"] for e in data] for data in errors] == [[16], []]
    assert slow.dropped > 0


# ─── A8 ────────────────────────────────────────────────────────────────────


async def test_a8_clientes_nao_assinam_nem_cancelam(rig: Rig) -> None:
    before = list(rig.pub_sub.subscribe_calls)

    client = rig.stream.add_client()
    assert client is not None
    rig.stream.remove_client(client)

    assert rig.pub_sub.subscribe_calls == before
    assert rig.pub_sub.unsubscribed == []
    assert rig.pub_sub.sent == []


# ─── Limite, desligamento e métricas ──────────────────────────────────────


async def test_limite_de_clientes(factory: FakeConnectionFactory) -> None:
    rig = await _rig(factory, max_clients=1)

    assert rig.stream.add_client() is not None
    assert rig.stream.add_client() is None
    await rig.stream.stop()


async def test_stop_fecha_com_1001(factory: FakeConnectionFactory) -> None:
    rig = await _rig(factory)
    client = rig.stream.add_client()
    assert client is not None
    client.drain()

    await rig.stream.stop()

    message = await client.next()
    assert (message.kind, message.code, message.reason) == ("close", 1001, "shutdown")


async def test_metricas_por_topico_e_por_cliente(
    rig: Rig, caplog: pytest.LogCaptureFixture
) -> None:
    client = rig.stream.add_client()
    assert client is not None
    rig.low()
    rig.low()
    rig.sport()
    rig.multi()
    rig.error("add_error", [1, 300, 16])
    rig.mono.advance(1.0)

    with caplog.at_level(logging.INFO, logger="app.robot.state_stream"):
        summary = rig.stream.emit_metrics()

    assert summary["received"] == {
        "low_state": 2,
        "sport_state": 1,
        "multiple_state": 1,
        "errors": 1,
    }
    assert summary["rate_hz"]["low_state"] == pytest.approx(2.0)
    assert summary["clients"][0]["dropped"] > 0
    assert "state_metrics" in caplog.text
    client.drain()
    assert rig.stream.emit_metrics()["clients"][0]["sent"] > 0


async def test_publish_event_e_section_para_specs_futuras(rig: Rig) -> None:
    client = rig.stream.add_client()
    assert client is not None
    client.drain()

    rig.stream.publish_event("speaker", {"state": "playing"}, ts=5.0)
    rig.stream.publish_section("audio_player", {"volume": 3}, ts=6.0)
    rig.stream.publish_section("audio_player", {"volume": 4}, ts=7.0)

    frames = _frames(client)
    assert [(f["topic"], f["data"]) for f in frames] == [
        ("speaker", {"state": "playing"}),
        ("audio_player", {"volume": 4}),
    ]


async def test_snapshot_provider_entra_antes_de_errors(rig: Rig) -> None:
    rig.stream.add_snapshot_provider(lambda: [("audio_player", 9.0, {"ok": True})])

    client = rig.stream.add_client()
    assert client is not None

    assert _topics(client) == ["connection", "audio_player", "errors"]
