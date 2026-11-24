"""F-003 A12b: `disableTrafficSaving` com refcount comum a LiDAR, telemetria e vídeo."""

import asyncio
from collections.abc import AsyncIterator

import pytest

from app.robot.connection import ConnectionState
from app.robot.lidar import LidarStream
from app.robot.link import RobotLink
from app.robot.streams import TrafficSaving
from app.robot.video import VideoStream
from tests.fakes import FakeConnectionFactory, FakeDataChannel, FakeVideoTrack

TIMEOUT_S = 0.2


@pytest.fixture
def datachannel(factory: FakeConnectionFactory) -> FakeDataChannel:
    return factory.connection.datachannel


@pytest.fixture
async def streams(
    factory: FakeConnectionFactory,
) -> AsyncIterator[tuple[RobotLink, LidarStream, VideoStream]]:
    factory.connection.video_track = FakeVideoTrack()
    link = RobotLink(factory)
    traffic = TrafficSaving(TIMEOUT_S)
    lidar = LidarStream(
        link,
        max_clients=2,
        client_queue=2,
        decode_queue=2,
        request_timeout_s=TIMEOUT_S,
        telemetry_max_clients=1,
        metrics_interval_s=None,
        traffic=traffic,
    )
    video = VideoStream(
        link,
        traffic=traffic,
        max_clients=2,
        client_queue=1,
        encode_queue=1,
        max_fps=0.0,
        jpeg_quality=80,
        stall_s=3.0,
        metrics_interval_s=None,
        stall_check_s=None,
    )
    lidar.start()
    video.start()
    await link.connect()
    yield link, lidar, video
    await video.stop()
    await lidar.stop()


async def _idle(lidar: LidarStream, video: VideoStream) -> None:
    for _ in range(3):
        await lidar.wait_idle()
        await video.wait_idle()
        await asyncio.sleep(0)


async def test_a12b_a_true_uma_vez_com_lidar_e_video(
    streams: tuple[RobotLink, LidarStream, VideoStream], datachannel: FakeDataChannel
) -> None:
    _, lidar, video = streams
    assert lidar.add_client() is not None
    assert video.add_client() is not None
    await _idle(lidar, video)

    assert datachannel.traffic_saving_calls == [True]


async def test_a12b_b_c_false_so_quando_sai_o_ultimo_das_tres_rotas(
    streams: tuple[RobotLink, LidarStream, VideoStream], datachannel: FakeDataChannel
) -> None:
    _, lidar, video = streams
    lidar_client = lidar.add_client()
    telemetry = lidar.add_telemetry_client()
    video_client = video.add_client()
    assert lidar_client is not None
    assert telemetry is not None
    assert video_client is not None
    await _idle(lidar, video)

    lidar.remove_client(lidar_client)
    lidar.remove_telemetry_client(telemetry)
    await _idle(lidar, video)
    assert datachannel.traffic_saving_calls == [True]

    video.remove_client(video_client)
    await _idle(lidar, video)
    assert datachannel.traffic_saving_calls == [True, False]


async def test_a12b_b_video_saindo_primeiro_nao_corta_o_lidar(
    streams: tuple[RobotLink, LidarStream, VideoStream], datachannel: FakeDataChannel
) -> None:
    _, lidar, video = streams
    lidar_client = lidar.add_client()
    video_client = video.add_client()
    assert lidar_client is not None
    assert video_client is not None
    await _idle(lidar, video)

    video.remove_client(video_client)
    await _idle(lidar, video)
    assert datachannel.traffic_saving_calls == [True]

    lidar.remove_client(lidar_client)
    await _idle(lidar, video)
    assert datachannel.traffic_saving_calls == [True, False]


async def test_a12b_d_reconexao_chama_true_de_novo_uma_vez(
    streams: tuple[RobotLink, LidarStream, VideoStream], datachannel: FakeDataChannel
) -> None:
    link, lidar, video = streams
    assert lidar.add_client() is not None
    assert video.add_client() is not None
    await _idle(lidar, video)

    await link.disconnect()
    link.state.update(ConnectionState.reconnecting, reason="retry")
    await link.connect()
    await _idle(lidar, video)

    assert datachannel.traffic_saving_calls == [True, True]


@pytest.mark.parametrize("result", ["hang", False, RuntimeError("falhou")])
async def test_a12b_e_falha_no_traffic_saving_fecha_o_video_com_1011(
    streams: tuple[RobotLink, LidarStream, VideoStream],
    datachannel: FakeDataChannel,
    result: object,
) -> None:
    _, lidar, video = streams
    datachannel.traffic_saving_result = result  # type: ignore[assignment]
    client = video.add_client()
    assert client is not None
    await _idle(lidar, video)

    closes = [m for m in client.drain_messages() if m.kind == "close"]
    assert [(m.code, m.reason) for m in closes] == [(1011, "video_unavailable")]
    assert datachannel.switch_video_calls == []
    await asyncio.sleep(0.05)
    assert datachannel.traffic_saving_calls == [True]
