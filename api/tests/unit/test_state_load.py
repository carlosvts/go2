"""F-004 A9: o `/ws/state` sob carga não atrasa o `move`.

Pior caso sintético: `LOW_STATE`, `SPORT_MOD_STATE` e `MULTIPLE_STATE` a
100 Hz cada, `GO2_STATE_MAX_CLIENTS` clientes lendo tudo. O `move` é simulado
por um laço de `asyncio.sleep` no período de `GO2_MOVE_RATE_HZ` (padrão), no
mesmo event loop da app. Não mede o robô (A11).
"""

import asyncio
import gc
import threading
import time
from collections.abc import Iterator
from contextlib import ExitStack

import numpy as np
import pytest
from fastapi.testclient import TestClient
from starlette.testclient import WebSocketTestSession

from app.config import Settings
from app.main import create_app
from app.robot.unitree import RTC_TOPIC
from tests.fakes import FakeConnectionFactory
from tests.state_payloads import low_state, multiple_state, sport_state

MEASURE_S = 3.0
PERIOD_S = 1.0 / Settings.model_fields["move_rate_hz"].default
SOURCE_HZ = 100.0


@pytest.fixture(autouse=True)
def _isolated_heap() -> Iterator[None]:
    """Tira do GC o lixo dos testes anteriores, só durante a medida (ver F-003)."""
    gc.collect()
    gc.freeze()
    yield
    gc.unfreeze()


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
def test_a9_estado_a_100_hz_com_clientes_nao_atrasa_o_move(
    factory: FakeConnectionFactory, settings: Settings
) -> None:
    max_clients = Settings.model_fields["state_max_clients"].default
    app = create_app(
        settings.model_copy(
            update={"move_rate_hz": Settings.model_fields["move_rate_hz"].default}
        ),
        connection_factory=factory,
    )
    pub_sub = factory.pub_sub
    payloads = {
        RTC_TOPIC["LOW_STATE"]: low_state(
            motor_state=[low_state()["motor_state"][0]] * 20
        ),
        RTC_TOPIC["SPORT_MOD_STATE"]: sport_state(),
        RTC_TOPIC["MULTIPLE_STATE"]: multiple_state(),
    }
    received = [0] * max_clients
    stop = threading.Event()
    published = [0]

    with TestClient(app) as client:
        assert client.portal is not None
        baseline = client.portal.call(_intervals, MEASURE_S)

        async def feed() -> None:
            while not stop.is_set():
                for topic, data in payloads.items():
                    pub_sub.publish_state(topic, data)
                published[0] += 1
                await asyncio.sleep(1 / SOURCE_HZ)

        with ExitStack() as stack:
            sockets = [
                stack.enter_context(client.websocket_connect("/ws/state"))
                for _ in range(max_clients)
            ]

            def read(index: int, ws: WebSocketTestSession) -> None:
                while not stop.is_set():
                    try:
                        ws.receive_text()
                    except Exception:
                        return
                    received[index] += 1

            readers = [
                threading.Thread(target=read, args=(i, ws), daemon=True)
                for i, ws in enumerate(sockets)
            ]
            for reader in readers:
                reader.start()
            client.portal.start_task_soon(feed)
            time.sleep(0.3)
            start = published[0]
            loaded = client.portal.call(_intervals, MEASURE_S)
            rate = (published[0] - start) / MEASURE_S
            stop.set()

    p99_base, p99_load = _p99_deviation(baseline), _p99_deviation(loaded)
    report = (
        f"período {PERIOD_S * 1000:.1f} ms; p99 desvio base {p99_base * 1000:.2f} ms,"
        f" com estado {p99_load * 1000:.2f} ms; máx {max(loaded) * 1000:.1f} ms;"
        f" {rate:.0f} rodadas/s por tópico; recebidos {received}"
    )
    print(report)
    assert rate > SOURCE_HZ * 0.5, f"carga abaixo do pedido: {report}"
    assert min(received) > 0, f"cliente não recebeu: {report}"
    assert p99_load <= p99_base + 0.10 * PERIOD_S, report
    assert max(loaded) <= 2 * PERIOD_S, report
