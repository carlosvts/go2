"""F-001 A8: o decoder trabalhando sem parar não atrasa o reenvio do `move`.

Pior caso independente da taxa do robô: a fila do decoder fica sempre cheia.
O `move` é simulado por um laço de `asyncio.sleep` no período de
`GO2_MOVE_RATE_HZ` (padrão), como o de `MoveController._resend`.

PROVISÓRIO: a spec manda usar o payload real de maior `n_points` gravado no
H1. Até lá, o payload é sintético (32 fatias z, 10% de bytes ocupados, ~26 mil
pontos), escolhido pelo teste e não medido no robô.
"""

import asyncio
import time

import numpy as np
import pytest

from app.config import Settings
from app.robot.lidar import LIDAR_TOPIC, LidarStream
from app.robot.link import RobotLink
from app.robot.unitree import decode_points
from tests.fakes import FakeConnectionFactory, FakePubSub
from tests.lidar_payloads import lidar_message, voxel_bitmap

MEASURE_S = 3.0
PERIOD_S = 1.0 / Settings.model_fields["move_rate_hz"].default


async def _intervals(duration_s: float) -> list[float]:
    intervals: list[float] = []
    last = time.monotonic()
    deadline = last + duration_s
    while last < deadline:
        await asyncio.sleep(PERIOD_S)
        now = time.monotonic()
        intervals.append(now - last)
        last = now
    return intervals


def _p99_deviation(intervals: list[float]) -> float:
    return float(np.percentile([abs(i - PERIOD_S) for i in intervals], 99))


@pytest.mark.slow
async def test_a8_decoder_sem_parar_nao_atrasa_o_move(
    factory: FakeConnectionFactory, pub_sub: FakePubSub
) -> None:
    baseline = await _intervals(MEASURE_S)

    decoded = 0

    def counting_decoder(*args: object) -> np.ndarray:
        nonlocal decoded
        decoded += 1
        return decode_points(*args)  # type: ignore[arg-type]

    link = RobotLink(factory)
    await link.connect()
    stream = LidarStream(
        link,
        max_clients=1,
        client_queue=2,
        decode_queue=2,
        request_timeout_s=0.2,
        decoder=counting_decoder,
    )
    stream.start()
    message = lidar_message(voxel_bitmap(z_slices=32, density=0.1, seed=3))

    async def feed() -> None:
        while True:
            pub_sub.subscriptions[LIDAR_TOPIC](message)
            await asyncio.sleep(0.002)

    try:
        assert stream.add_client() is not None
        await stream.wait_idle()
        feeder = asyncio.create_task(feed())
        loaded = await _intervals(MEASURE_S)
        feeder.cancel()
    finally:
        await stream.stop()

    p99_base, p99_load = _p99_deviation(baseline), _p99_deviation(loaded)
    report = (
        f"período {PERIOD_S * 1000:.1f} ms; p99 desvio base {p99_base * 1000:.2f} ms,"
        f" com decoder {p99_load * 1000:.2f} ms; máx {max(loaded) * 1000:.1f} ms;"
        f" {decoded} decodificações"
    )
    print(report)
    assert decoded > MEASURE_S * 5, f"decoder não ficou sob carga: {report}"
    assert p99_load <= p99_base + 0.10 * PERIOD_S, report
    assert max(loaded) <= 2 * PERIOD_S, report
