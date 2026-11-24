"""F-003 A14: o JPEG sem parar e o envio a 2 clientes não atrasam o `move`.

Pior caso independente da taxa do robô: a fila do codificador fica sempre
cheia de quadros 1280×720 sintéticos, e dois clientes WebSocket leem tudo.
O `move` é simulado por um laço de `asyncio.sleep` no período de
`GO2_MOVE_RATE_HZ` (padrão), no mesmo event loop da app.

Não cobre o RTP/SRTP do aiortc no loop: passar aqui não prevê A17/A18.
"""

import asyncio
import gc
import threading
import time
from collections.abc import Iterator

import numpy as np
import pytest
from fastapi.testclient import TestClient
from starlette.testclient import WebSocketTestSession

from app.config import Settings
from app.main import create_app
from tests.fakes import FakeConnectionFactory, FakeVideoTrack
from tests.video_frames import video_frame

MEASURE_S = 3.0
PERIOD_S = 1.0 / Settings.model_fields["move_rate_hz"].default


@pytest.fixture(autouse=True)
def _isolated_heap() -> Iterator[None]:
    """Tira do GC o lixo dos testes anteriores, só durante a medida.

    Na suíte completa, as pausas do coletor (maiores com OpenCV/av
    carregados) criavam picos que não vêm do código medido. Os limites não
    mudam. A api real também carrega OpenCV: o efeito do GC lá é medido no
    robô (F-003 A17/A18), não aqui.
    """
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
def test_a14_jpeg_sem_parar_nao_atrasa_o_move(
    factory: FakeConnectionFactory, settings: Settings
) -> None:
    track = FakeVideoTrack()
    factory.connection.video_track = track
    frame = video_frame(width=1280, height=720)
    app = create_app(
        settings.model_copy(update={"move_rate_hz": 30.0, "video_max_clients": 2}),
        connection_factory=factory,
    )
    received = [0, 0]
    stop = threading.Event()

    with TestClient(app) as client:
        assert client.portal is not None
        baseline = client.portal.call(_intervals, MEASURE_S)

        async def feed() -> None:
            while not stop.is_set():
                track.put(frame)
                await asyncio.sleep(0.002)

        with (
            client.websocket_connect("/ws/video") as first,
            client.websocket_connect("/ws/video") as second,
        ):

            def read(index: int, ws: WebSocketTestSession) -> None:
                while not stop.is_set():
                    try:
                        message = ws.receive()
                    except Exception:
                        return
                    if message.get("bytes") is not None:
                        received[index] += 1

            readers = [
                threading.Thread(target=read, args=(i, ws), daemon=True)
                for i, ws in enumerate((first, second))
            ]
            for reader in readers:
                reader.start()
            client.portal.start_task_soon(feed)
            time.sleep(0.3)
            loaded = client.portal.call(_intervals, MEASURE_S)
            stop.set()
            robot = app.state.robot
            encoded = robot.video.encoded_total()

    p99_base, p99_load = _p99_deviation(baseline), _p99_deviation(loaded)
    report = (
        f"período {PERIOD_S * 1000:.1f} ms; p99 desvio base {p99_base * 1000:.2f} ms,"
        f" com vídeo {p99_load * 1000:.2f} ms; máx {max(loaded) * 1000:.1f} ms;"
        f" {encoded} JPEGs; recebidos {received}"
    )
    print(report)
    assert encoded > MEASURE_S * 5, f"codificador não ficou sob carga: {report}"
    assert min(received) > 0, f"cliente não recebeu: {report}"
    assert p99_load <= p99_base + 0.10 * PERIOD_S, report
    assert max(loaded) <= 2 * PERIOD_S, report
