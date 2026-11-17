"""Telemetria do LiDAR: extras, métricas, falha e filas (F-002)."""

import asyncio
import json
import math
import threading
from collections.abc import AsyncIterator
from typing import Any

import numpy as np
import pytest

from app.robot.connection import ConnectionState
from app.robot.lidar import (
    LidarStream,
    TelemetryClient,
    to_json_safe,
)
from app.robot.link import RobotLink
from app.robot.unitree import RTC_TOPIC, decode_points
from tests.fakes import FakeConnectionFactory, FakeDataChannel, FakePubSub
from tests.lidar_payloads import LIDAR_TOPIC, lidar_message, voxel_bitmap

POSE = RTC_TOPIC["ROBOTODOM"]
STATE = RTC_TOPIC["ULIDAR_STATE"]
EXTRAS = (POSE, STATE)


class Clock:
    """Relógio monotônico controlado pelo teste."""

    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
async def link(factory: FakeConnectionFactory) -> RobotLink:
    instance = RobotLink(factory)
    await instance.connect()
    return instance


@pytest.fixture
def datachannel(factory: FakeConnectionFactory) -> FakeDataChannel:
    return factory.connection.datachannel


@pytest.fixture
def clock() -> Clock:
    return Clock()


def _stream(link: RobotLink, clock: Clock, **overrides: Any) -> LidarStream:
    options: dict[str, Any] = {
        "max_clients": 2,
        "client_queue": 2,
        "decode_queue": 2,
        "request_timeout_s": 0.2,
        "telemetry_max_clients": 2,
        "telemetry_queue": 16,
        "metrics_interval_s": None,  # janela disparada pelo teste
        "monotonic": clock,
    }
    options.update(overrides)
    return LidarStream(link, **options)


@pytest.fixture
async def stream(link: RobotLink, clock: Clock) -> AsyncIterator[LidarStream]:
    instance = _stream(link, clock)
    instance.start()
    yield instance
    await instance.stop()


def _drain(client: TelemetryClient) -> list[dict[str, Any]]:
    """Retira tudo o que está pronto para envio, sem esperar."""
    return [json.loads(text) for text in client.drain()]


def _by_topic(frames: list[dict[str, Any]], topic: str) -> list[dict[str, Any]]:
    return [f for f in frames if f["topic"] == topic]


def _metrics(client: TelemetryClient) -> dict[str, Any]:
    [frame] = _by_topic(_drain(client), "lidar_metrics")
    data: dict[str, Any] = frame["data"]
    return data


async def _decoded(stream: LidarStream, count: int) -> None:
    for _ in range(200):
        if stream.decoded_total() >= count:
            return
        await asyncio.sleep(0.01)
    raise AssertionError("decoder não processou a tempo")


# ─── A1 ─────────────────────────────────────────────────────────────────────


async def test_a1_robo_fora_do_ar_mantem_telemetria_e_metricas(
    factory: FakeConnectionFactory, clock: Clock
) -> None:
    stream = _stream(RobotLink(factory), clock)
    stream.start()
    try:
        client = stream.add_telemetry_client()
        assert client is not None
        await stream.wait_idle()
        stream.emit_metrics()

        frames = _drain(client)
        assert frames[0]["topic"] == "connection"
        assert frames[0]["data"] == {"state": "disconnected"}
        metrics = _by_topic(frames, "lidar_metrics")[0]["data"]
        assert metrics["active"] is False
        assert metrics["received"] == 0
        assert not client.is_closed
    finally:
        await stream.stop()


# ─── A2 a A5: ciclo de vida das assinaturas ─────────────────────────────────


async def test_a2_telemetria_sozinha_ativa_lidar_e_extras(
    stream: LidarStream, pub_sub: FakePubSub, datachannel: FakeDataChannel
) -> None:
    stream.add_telemetry_client()
    await stream.wait_idle()

    assert datachannel.traffic_saving_calls == [True]
    assert datachannel.decoder is not None
    assert pub_sub.subscribe_calls == [LIDAR_TOPIC, *EXTRAS]


async def test_a3_saida_da_telemetria_cancela_so_extras(
    stream: LidarStream, pub_sub: FakePubSub, datachannel: FakeDataChannel
) -> None:
    lidar = stream.add_client()
    telemetry = stream.add_telemetry_client()
    assert lidar is not None
    assert telemetry is not None
    await stream.wait_idle()

    stream.remove_telemetry_client(telemetry)
    await stream.wait_idle()
    assert sorted(pub_sub.unsubscribed) == sorted(EXTRAS)
    assert all(topic not in pub_sub.subscriptions for topic in EXTRAS)
    assert LIDAR_TOPIC in pub_sub.subscriptions

    stream.remove_client(lidar)
    await stream.wait_idle()
    assert LIDAR_TOPIC not in pub_sub.subscriptions
    assert datachannel.traffic_saving_calls == [True, False]


async def test_a4_so_lidar_nao_assina_extras(
    stream: LidarStream, pub_sub: FakePubSub
) -> None:
    stream.add_client()
    await stream.wait_idle()

    assert pub_sub.subscribe_calls == [LIDAR_TOPIC]


async def test_a5_telemetria_com_lidar_ja_ativo_assina_so_extras(
    stream: LidarStream, pub_sub: FakePubSub, datachannel: FakeDataChannel
) -> None:
    stream.add_client()
    await stream.wait_idle()
    stream.add_telemetry_client()
    await stream.wait_idle()

    assert datachannel.traffic_saving_calls == [True]
    assert pub_sub.subscribe_calls == [LIDAR_TOPIC, *EXTRAS]


# ─── A6: reconexão ──────────────────────────────────────────────────────────


async def test_a6_reconexao_reassina_lidar_e_extras(
    stream: LidarStream, link: RobotLink, pub_sub: FakePubSub
) -> None:
    lidar = stream.add_client()
    telemetry = stream.add_telemetry_client()
    assert lidar is not None
    assert telemetry is not None
    await stream.wait_idle()
    lidar.pending_texts()
    _drain(telemetry)

    await link.disconnect()
    link.state.update(ConnectionState.reconnecting, reason="retry")
    await link.connect()
    await stream.wait_idle()

    expected = ["disconnected", "reconnecting", "connected"]
    assert [json.loads(t)["data"]["state"] for t in lidar.pending_texts()] == expected
    states = [f["data"]["state"] for f in _by_topic(_drain(telemetry), "connection")]
    assert states == expected
    assert pub_sub.subscribe_calls == [LIDAR_TOPIC, *EXTRAS] * 2
    assert not lidar.is_closed
    assert not telemetry.is_closed


# ─── A7: falha na ativação ──────────────────────────────────────────────────


async def test_a7_falha_fecha_lidar_e_mantem_telemetria(
    stream: LidarStream, datachannel: FakeDataChannel, pub_sub: FakePubSub
) -> None:
    datachannel.traffic_saving_result = False
    lidar = stream.add_client()
    telemetry = stream.add_telemetry_client()
    assert lidar is not None
    assert telemetry is not None
    await stream.wait_idle()

    assert lidar.is_closed
    assert not telemetry.is_closed
    stream.emit_metrics()
    metrics = _metrics(telemetry)
    assert metrics["active"] is False
    assert metrics["last_error"] == "activation_failed"
    assert pub_sub.subscribe_calls == []

    # Sem nova tentativa sozinha, mesmo com a telemetria presente.
    await asyncio.sleep(0.05)
    await stream.wait_idle()
    assert datachannel.traffic_saving_calls == [True]

    # Um cliente novo tenta de novo; se der certo, o erro some.
    datachannel.traffic_saving_result = True
    stream.add_client()
    await stream.wait_idle()
    assert datachannel.traffic_saving_calls == [True, True]
    stream.emit_metrics()
    metrics = _metrics(telemetry)
    assert metrics["active"] is True
    assert metrics["last_error"] is None


# ─── A8: corrida ────────────────────────────────────────────────────────────


@pytest.mark.parametrize("telemetry_stays", [True, False])
async def test_a8_telemetria_entra_ou_sai_durante_a_ativacao(
    stream: LidarStream,
    pub_sub: FakePubSub,
    datachannel: FakeDataChannel,
    telemetry_stays: bool,
) -> None:
    gate = asyncio.Event()
    original = datachannel.disableTrafficSaving

    async def slow(switch: bool) -> bool:
        await gate.wait()
        return await original(switch)

    datachannel.disableTrafficSaving = slow  # type: ignore[method-assign]
    stream.add_client()
    await asyncio.sleep(0)
    telemetry = stream.add_telemetry_client()
    assert telemetry is not None
    if not telemetry_stays:
        stream.remove_telemetry_client(telemetry)
    gate.set()
    await stream.wait_idle()

    subscribed = all(topic in pub_sub.subscriptions for topic in EXTRAS)
    assert subscribed is telemetry_stays
    assert LIDAR_TOPIC in pub_sub.subscriptions


# ─── A9: conversão para JSON ────────────────────────────────────────────────


def test_a9_conversao_recursiva_para_json_estrito() -> None:
    value = {
        "data": b"\x00\x01",
        "nested": [bytearray(b"ab"), {"x": math.nan, "y": math.inf, "z": -math.inf}],
        "np": np.float32(1.5),
        "arr": np.array([1, 2]),
        "obj": object(),
        3: (1, 2),
    }

    safe = to_json_safe(value)

    assert safe == {
        "data": {"base64": "AAE="},
        "nested": [
            {"base64": "YWI="},
            {
                "x": {"nonfinite": "nan"},
                "y": {"nonfinite": "inf"},
                "z": {"nonfinite": "-inf"},
            },
        ],
        "np": 1.5,
        "arr": [1, 2],
        "obj": {"unserializable": "object"},
        "3": [1, 2],
    }
    json.dumps(safe, allow_nan=False)


async def test_a9_extras_viram_lidar_pose_e_lidar_state(
    stream: LidarStream, pub_sub: FakePubSub
) -> None:
    telemetry = stream.add_telemetry_client()
    assert telemetry is not None
    await stream.wait_idle()
    _drain(telemetry)

    pub_sub.publish_state(POSE, {"position": [1.0, 2.0, 0.3], "raw": b"\xff"})
    pub_sub.publish_state(STATE, {"cloud_frequency": math.nan})

    frames = _drain(telemetry)
    assert [f["topic"] for f in frames] == ["lidar_pose", "lidar_state"]
    assert frames[0]["data"] == {"position": [1.0, 2.0, 0.3], "raw": {"base64": "/w=="}}
    assert frames[1]["data"] == {"cloud_frequency": {"nonfinite": "nan"}}
    assert isinstance(frames[0]["ts"], float)


# ─── A10 e A11: métricas ────────────────────────────────────────────────────


async def test_a10_metricas_da_janela(
    stream: LidarStream, pub_sub: FakePubSub, clock: Clock
) -> None:
    telemetry = stream.add_telemetry_client()
    assert telemetry is not None
    await stream.wait_idle()
    stream.emit_metrics()  # fecha a janela da ativação
    _drain(telemetry)

    bitmaps = [
        voxel_bitmap(density=d, seed=i) for i, d in enumerate((0.01, 0.02, 0.03))
    ]
    expected_points = []
    for offset, bitmap in zip((0.0, 0.1, 0.3), bitmaps, strict=True):
        clock.now = 200.0 + offset
        message = lidar_message(bitmap, origin=(1.0, 2.0, 3.0), resolution=0.1)
        pub_sub.subscriptions[LIDAR_TOPIC](message)
        expected_points.append(
            len(
                decode_points(
                    message["data"]["data"], len(bitmap), (1.0, 2.0, 3.0), 0.1
                )
            )
        )
        await _decoded(stream, len(expected_points))
    clock.now = 200.0 + 0.5
    pub_sub.subscriptions[LIDAR_TOPIC]({"type": "msg", "topic": LIDAR_TOPIC})
    clock.now = 201.0

    stream.emit_metrics()
    metrics = _metrics(telemetry)

    assert metrics["received"] == 4
    assert metrics["malformed"] == 1
    assert metrics["decoded"] == 3
    assert metrics["seq"] == {"first": 0, "last": 3}
    interval = metrics["interval_ms"]
    assert interval["min"] == pytest.approx(100.0)
    assert interval["max"] == pytest.approx(200.0)
    assert interval["mean"] == pytest.approx(500.0 / 3)
    assert metrics["n_points"]["min"] == min(expected_points)
    assert metrics["n_points"]["max"] == max(expected_points)
    assert metrics["src_size"] == {"min": 8192, "mean": 8192.0, "max": 8192}
    assert metrics["resolution"] == pytest.approx(0.1)
    assert metrics["origin"] == [1.0, 2.0, 3.0]
    assert metrics["window_s"] > 0
    assert metrics["rate_hz"] == pytest.approx(4 / metrics["window_s"])
    assert metrics["decode_ms"]["min"] >= 0
    assert metrics["pipeline_ms"]["min"] >= 0
    assert metrics["active"] is True
    assert metrics["clients"] == {"lidar": 0, "telemetry": 1}
    assert metrics["dropped"] == 0


async def test_a11_intervalo_zera_na_desativacao_e_na_reconexao(
    stream: LidarStream, link: RobotLink, pub_sub: FakePubSub, clock: Clock
) -> None:
    telemetry = stream.add_telemetry_client()
    assert telemetry is not None
    await stream.wait_idle()
    clock.now = 300.0
    pub_sub.subscriptions[LIDAR_TOPIC](lidar_message(voxel_bitmap(density=0.0)))

    await link.disconnect()
    await link.connect()
    await stream.wait_idle()
    clock.now = 900.0
    pub_sub.subscriptions[LIDAR_TOPIC](lidar_message(voxel_bitmap(density=0.0)))

    stream.emit_metrics()
    metrics = _metrics(telemetry)
    assert metrics["received"] == 2
    assert metrics["interval_ms"] == {"min": None, "mean": None, "max": None}

    stream.emit_metrics()
    empty = _metrics(telemetry)
    assert empty["received"] == 0
    assert empty["n_points"] == {"min": None, "mean": None, "max": None}
    assert empty["resolution"] is None


# ─── A12: descartes ─────────────────────────────────────────────────────────


async def test_a12_descartes_e_erros_contados(
    link: RobotLink, pub_sub: FakePubSub, clock: Clock
) -> None:
    release = threading.Event()

    def blocked(*args: Any) -> Any:
        release.wait(timeout=2.0)
        return decode_points(*args)

    stream = _stream(link, clock, decoder=blocked, decode_queue=2, client_queue=1)
    stream.start()
    try:
        lidar = stream.add_client()  # nunca lê
        telemetry = stream.add_telemetry_client()
        assert lidar is not None
        assert telemetry is not None
        await stream.wait_idle()
        stream.emit_metrics()
        _drain(telemetry)

        for _ in range(5):
            pub_sub.subscriptions[LIDAR_TOPIC](lidar_message(voxel_bitmap(density=0.0)))
        broken = lidar_message(voxel_bitmap())
        broken["data"]["data"] = b"\xf0"  # lz4 inválido
        release.set()
        await _decoded(stream, 2)
        pub_sub.subscriptions[LIDAR_TOPIC](broken)
        for _ in range(100):
            await asyncio.sleep(0.01)
            if stream.decode_errors_total() == 1:
                break

        stream.emit_metrics()
        metrics = _metrics(telemetry)
    finally:
        release.set()
        await stream.stop()

    # 5 válidas numa fila de 2 sem o worker rodar: 3 descartadas antes do decoder.
    assert metrics["dropped_decode_queue"] == 3
    assert metrics["decoded"] == 2
    # Cliente de /ws/lidar com fila 1 que não lê: 2 frames, 1 descartado.
    assert metrics["dropped_lidar_clients"] == 1
    assert metrics["decode_errors"] == 1


# ─── A13: cliente de telemetria lento ───────────────────────────────────────


async def test_a13_fila_por_topico_e_dropped_acumulado(
    link: RobotLink, pub_sub: FakePubSub, clock: Clock
) -> None:
    stream = _stream(link, clock, telemetry_queue=3)
    stream.start()
    try:
        telemetry = stream.add_telemetry_client()
        assert telemetry is not None
        await stream.wait_idle()

        for i in range(5):
            pub_sub.publish_state(POSE, {"i": i})
        for _ in range(4):
            stream.emit_metrics()
        stream.on_connection({"state": "connected", "reason": "teste"})

        frames = _drain(telemetry)
    finally:
        await stream.stop()

    topics = [f["topic"] for f in frames]
    assert topics.count("connection") == 2
    poses = _by_topic(frames, "lidar_pose")
    assert [p["data"]["i"] for p in poses] == [2, 3, 4]
    metrics = _by_topic(frames, "lidar_metrics")
    assert len(metrics) == 3
    # 2 poses + 1 métrica perdidas, todas contadas no primeiro envio.
    assert [m["data"]["dropped"] for m in metrics] == [3, 0, 0]


# ─── A14: limite ────────────────────────────────────────────────────────────


async def test_a14_limite_de_clientes_de_telemetria(
    link: RobotLink, clock: Clock
) -> None:
    stream = _stream(link, clock, telemetry_max_clients=1, max_clients=1)
    assert stream.add_telemetry_client() is not None
    assert stream.add_telemetry_client() is None
    assert stream.add_client() is not None

    assert _stream(link, clock, telemetry_max_clients=0).add_telemetry_client() is None


async def test_janela_automatica_emite_metricas(link: RobotLink) -> None:
    stream = LidarStream(
        link,
        max_clients=1,
        client_queue=2,
        decode_queue=2,
        request_timeout_s=0.2,
        metrics_interval_s=0.02,
    )
    stream.start()
    try:
        telemetry = stream.add_telemetry_client()
        assert telemetry is not None
        await asyncio.sleep(0.1)
        frames = _drain(telemetry)
    finally:
        await stream.stop()

    assert len(_by_topic(frames, "lidar_metrics")) >= 2
