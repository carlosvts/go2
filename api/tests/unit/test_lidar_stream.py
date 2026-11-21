"""Refcount, ativação, filas e decodificação do stream de LiDAR (F-001)."""

import asyncio
import json
import threading
from collections.abc import AsyncIterator, Callable
from typing import Any

import lz4.block
import numpy as np
import pytest
from numpy.typing import NDArray
from unitree_webrtc_connect.webrtc_datachannel import WebRTCDataChannel

from app.robot.connection import ConnectionState
from app.robot.lidar import (
    FRAME_HEADER,
    ClientMessage,
    LidarClient,
    LidarStream,
)
from app.robot.link import RobotLink
from app.robot.unitree import decode_points, install_raw_lidar_decoder
from tests.fakes import FakeConnectionFactory, FakeDataChannel, FakePubSub
from tests.lidar_payloads import (
    LIDAR_TOPIC,
    lib_lidar_buffer,
    lidar_message,
    voxel_bitmap,
)

TIMEOUT_S = 0.2


@pytest.fixture
async def link(factory: FakeConnectionFactory) -> RobotLink:
    instance = RobotLink(factory)
    await instance.connect()
    return instance


@pytest.fixture
def datachannel(factory: FakeConnectionFactory) -> FakeDataChannel:
    return factory.connection.datachannel


def _stream(
    link: RobotLink,
    *,
    max_clients: int = 2,
    client_queue: int = 2,
    decode_queue: int = 2,
    decoder: Callable[..., NDArray[np.float64]] = decode_points,
) -> LidarStream:
    return LidarStream(
        link,
        max_clients=max_clients,
        client_queue=client_queue,
        decode_queue=decode_queue,
        request_timeout_s=TIMEOUT_S,
        decoder=decoder,
    )


@pytest.fixture
async def stream(link: RobotLink) -> AsyncIterator[LidarStream]:
    instance = _stream(link)
    instance.start()
    yield instance
    await instance.stop()


async def _settle(stream: LidarStream) -> None:
    """Espera ativação/desativação pendentes terminarem."""
    await stream.wait_idle()


async def _next(client: LidarClient) -> ClientMessage:
    return await asyncio.wait_for(client.next(), 2.0)


def _seq(frame: bytes) -> int:
    return int(FRAME_HEADER.unpack_from(frame, 0)[3])


async def _frames(client: LidarClient, count: int) -> list[bytes]:
    frames: list[bytes] = []
    while len(frames) < count:
        message = await _next(client)
        if message.kind == "bytes":
            assert isinstance(message.data, bytes)
            frames.append(message.data)
    return frames


def _texts(client: LidarClient) -> list[dict[str, Any]]:
    return [json.loads(text) for text in client.pending_texts()]


# ─── A3: decodificação fora do event loop, com a classe real da lib ─────────


async def test_a3_lz4_nunca_roda_na_thread_do_loop(
    stream: LidarStream,
    pub_sub: FakePubSub,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    threads: list[int] = []
    original = lz4.block.decompress

    def spy(*args: Any, **kwargs: Any) -> bytes:
        threads.append(threading.get_ident())
        return bytes(original(*args, **kwargs))

    monkeypatch.setattr(lz4.block, "decompress", spy)
    client = stream.add_client()
    assert client is not None
    await _settle(stream)

    # Data channel real da lib, sem rede: só o caminho que desmonta o binário.
    real = WebRTCDataChannel.__new__(WebRTCDataChannel)
    install_raw_lidar_decoder(real)
    parsed = real.deal_array_buffer(lib_lidar_buffer(voxel_bitmap(density=0.05)))
    pub_sub.subscriptions[LIDAR_TOPIC](parsed)

    [frame] = await _frames(client, 1)

    assert FRAME_HEADER.unpack_from(frame, 0)[5] > 0
    assert len(threads) == 1
    assert threads[0] != threading.get_ident()


# ─── A4: refcount ───────────────────────────────────────────────────────────


async def test_a4_assina_no_primeiro_cliente_e_cancela_no_ultimo(
    stream: LidarStream, pub_sub: FakePubSub, datachannel: FakeDataChannel
) -> None:
    first = stream.add_client()
    await _settle(stream)
    second = stream.add_client()
    await _settle(stream)

    assert pub_sub.subscribe_calls.count(LIDAR_TOPIC) == 1
    assert datachannel.traffic_saving_calls == [True]
    assert datachannel.decoder is not None

    assert first is not None
    assert second is not None
    stream.remove_client(first)
    await _settle(stream)
    assert pub_sub.unsubscribed == []

    stream.remove_client(second)
    await _settle(stream)
    assert pub_sub.unsubscribed == [LIDAR_TOPIC]
    assert LIDAR_TOPIC not in pub_sub.subscriptions
    assert datachannel.traffic_saving_calls == [True, False]


async def test_cliente_que_sai_durante_a_ativacao_desativa_no_fim(
    stream: LidarStream, pub_sub: FakePubSub, datachannel: FakeDataChannel
) -> None:
    client = stream.add_client()
    assert client is not None
    stream.remove_client(client)
    await _settle(stream)

    assert LIDAR_TOPIC not in pub_sub.subscriptions
    assert datachannel.traffic_saving_calls in ([], [True, False])


async def test_falha_ao_desfazer_traffic_saving_so_vai_para_o_log(
    stream: LidarStream, pub_sub: FakePubSub, datachannel: FakeDataChannel
) -> None:
    client = stream.add_client()
    assert client is not None
    await _settle(stream)
    datachannel.traffic_saving_result = "hang"

    stream.remove_client(client)
    await _settle(stream)

    assert LIDAR_TOPIC not in pub_sub.subscriptions
    assert datachannel.traffic_saving_calls == [True, False]


# ─── A5: robô fora do ar ────────────────────────────────────────────────────


async def test_a5_com_robo_fora_espera_sem_assinar(
    factory: FakeConnectionFactory, pub_sub: FakePubSub
) -> None:
    link = RobotLink(factory)
    stream = _stream(link)
    stream.start()
    try:
        client = stream.add_client()
        assert client is not None
        await _settle(stream)

        assert [t["data"]["state"] for t in _texts(client)] == ["disconnected"]
        assert pub_sub.subscribe_calls == []

        await link.connect()
        await _settle(stream)

        assert [t["data"]["state"] for t in _texts(client)] == ["connected"]
        assert LIDAR_TOPIC in pub_sub.subscriptions
        pub_sub.subscriptions[LIDAR_TOPIC](lidar_message(voxel_bitmap()))
        assert len(await _frames(client, 1)) == 1
    finally:
        await stream.stop()


# ─── A6: reconexão ──────────────────────────────────────────────────────────


async def test_a6_reconexao_reativa_sem_fechar_o_cliente(
    stream: LidarStream,
    link: RobotLink,
    pub_sub: FakePubSub,
    datachannel: FakeDataChannel,
) -> None:
    client = stream.add_client()
    assert client is not None
    await _settle(stream)
    client.pending_texts()

    await link.disconnect()
    link.state.update(ConnectionState.reconnecting, reason="retry")
    datachannel.decoder = None
    await link.connect()
    await _settle(stream)

    states = [t["data"]["state"] for t in _texts(client)]
    assert states == ["disconnected", "reconnecting", "connected"]
    assert not client.is_closed
    assert datachannel.decoder is not None
    assert pub_sub.subscribe_calls.count(LIDAR_TOPIC) == 2
    pub_sub.subscriptions[LIDAR_TOPIC](lidar_message(voxel_bitmap()))
    assert len(await _frames(client, 1)) == 1


# ─── A7: falha na ativação ──────────────────────────────────────────────────


@pytest.mark.parametrize(
    "result",
    ["hang", False, RuntimeError("canal fechou")],
    ids=["timeout", "resposta-nao-ok", "excecao"],
)
async def test_a7_falha_na_ativacao_fecha_com_1011(
    stream: LidarStream,
    pub_sub: FakePubSub,
    datachannel: FakeDataChannel,
    result: bool | Exception | str,
) -> None:
    datachannel.traffic_saving_result = result
    client = stream.add_client()
    assert client is not None

    # O loop segue livre durante a espera pelo robô.
    other = asyncio.create_task(asyncio.sleep(0, result="ok"))
    assert await asyncio.wait_for(other, TIMEOUT_S / 2) == "ok"

    messages = [await _next(client) for _ in range(2)]

    assert messages[-1].kind == "close"
    assert (messages[-1].code, messages[-1].reason) == (1011, "lidar_unavailable")
    assert LIDAR_TOPIC not in pub_sub.subscriptions
    await _settle(stream)
    assert datachannel.traffic_saving_calls == [True]


async def test_a7_nao_tenta_de_novo_sozinho_mas_novo_cliente_tenta(
    stream: LidarStream, datachannel: FakeDataChannel
) -> None:
    datachannel.traffic_saving_result = False
    stream.add_client()
    await _settle(stream)
    await asyncio.sleep(TIMEOUT_S)
    assert datachannel.traffic_saving_calls == [True]

    datachannel.traffic_saving_result = True
    stream.add_client()
    await _settle(stream)
    assert datachannel.traffic_saving_calls == [True, True]


# ─── A9 e A10: filas ────────────────────────────────────────────────────────


async def test_a9_cliente_lento_perde_os_antigos_e_nao_atrapalha_o_outro(
    stream: LidarStream, pub_sub: FakePubSub
) -> None:
    fast = stream.add_client()
    slow = stream.add_client()
    assert fast is not None
    assert slow is not None
    await _settle(stream)
    fast.pending_texts()
    slow.pending_texts()

    received: list[int] = []
    for _ in range(6):
        pub_sub.subscriptions[LIDAR_TOPIC](lidar_message(voxel_bitmap(density=0.01)))
        received += [_seq(f) for f in await _frames(fast, 1)]
    stream.on_connection({"state": "connected", "reason": "teste"})

    assert received == sorted(received)
    assert len(received) == 6
    # O frame de texto não entra na fila com descarte: chega aos dois.
    assert [t["topic"] for t in _texts(slow)] == ["connection"]
    assert [t["topic"] for t in _texts(fast)] == ["connection"]
    assert slow.pending_frame_count() == 2
    slow_frames = await _frames(slow, 2)
    assert [_seq(f) for f in slow_frames] == received[-2:]


async def test_a10_fila_do_decoder_e_limitada_e_preserva_ordem(
    link: RobotLink, pub_sub: FakePubSub
) -> None:
    release = threading.Event()

    def slow_decoder(*args: Any) -> NDArray[np.float64]:
        release.wait(timeout=2.0)
        return decode_points(*args)

    stream = _stream(link, decode_queue=2, client_queue=10, decoder=slow_decoder)
    stream.start()
    try:
        client = stream.add_client()
        assert client is not None
        await _settle(stream)
        for _ in range(8):
            pub_sub.subscriptions[LIDAR_TOPIC](lidar_message(voxel_bitmap()))
            assert stream.pending_decode_count() <= 2
        release.set()

        frames = await _frames(client, 2)

        # Fila de 2: das 8 mensagens só as duas mais novas chegam ao decoder.
        assert [_seq(f) for f in frames] == [6, 7]
        await asyncio.sleep(0.05)
        assert client.pending_frame_count() == 0
    finally:
        release.set()
        await stream.stop()


async def test_mensagem_malformada_e_descartada_sem_derrubar_o_stream(
    stream: LidarStream, pub_sub: FakePubSub
) -> None:
    client = stream.add_client()
    assert client is not None
    await _settle(stream)

    pub_sub.subscriptions[LIDAR_TOPIC]({"type": "msg", "topic": LIDAR_TOPIC})
    broken = lidar_message(voxel_bitmap())
    broken["data"]["data"] = b"\x00\x01"
    pub_sub.subscriptions[LIDAR_TOPIC](broken)
    pub_sub.subscriptions[LIDAR_TOPIC](lidar_message(voxel_bitmap()))

    [frame] = await _frames(client, 1)
    assert _seq(frame) == 2


# ─── A11: limite de clientes e convivência com o /status ────────────────────


async def test_a11_limite_de_clientes(link: RobotLink) -> None:
    stream = _stream(link, max_clients=1)
    assert stream.add_client() is not None
    assert stream.add_client() is None

    assert _stream(link, max_clients=0).add_client() is None


async def test_a11_ativacao_nao_mexe_nos_topicos_de_estado(
    factory: FakeConnectionFactory, settings: Any
) -> None:
    from app.robot.service import Go2Robot  # noqa: PLC0415
    from app.robot.unitree import RTC_TOPIC  # noqa: PLC0415

    robot = Go2Robot.from_settings(settings, factory)
    await robot.connect()
    robot.lidar.start()
    try:
        client = robot.lidar.add_client()
        assert client is not None
        await robot.lidar.wait_idle()
        robot.lidar.remove_client(client)
        await robot.lidar.wait_idle()

        pub_sub = factory.pub_sub
        assert RTC_TOPIC["LOW_STATE"] in pub_sub.subscriptions
        assert RTC_TOPIC["SPORT_MOD_STATE"] in pub_sub.subscriptions
        assert RTC_TOPIC["LOW_STATE"] not in pub_sub.unsubscribed
        pub_sub.publish_state(RTC_TOPIC["LOW_STATE"], {"bms_state": {"soc": 80}})
        assert robot.status().battery_percent == 80
    finally:
        await robot.lidar.stop()
        await robot.disconnect()
