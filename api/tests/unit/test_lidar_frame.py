"""Formato do frame binário do `/ws/lidar` (F-001, A1 e A2)."""

import numpy as np
from unitree_webrtc_connect.lidar.lidar_decoder_native import LidarDecoder

from app.robot.lidar import FRAME_HEADER, HEADER_LEN, RawLidarMessage, build_frame
from app.robot.unitree import decode_points
from tests.lidar_payloads import compress, lidar_metadata, voxel_bitmap


def _raw(bitmap: bytes, seq: int = 7, ts: float = 1234.5) -> RawLidarMessage:
    meta = lidar_metadata(bitmap)
    return RawLidarMessage(
        seq=seq,
        ts=ts,
        payload=compress(bitmap),
        src_size=meta["src_size"],
        origin=tuple(meta["origin"]),
        resolution=meta["resolution"],
    )


def _header(frame: bytes) -> tuple[object, ...]:
    return FRAME_HEADER.unpack_from(frame, 0)


def test_cabecalho_tem_40_bytes() -> None:
    assert FRAME_HEADER.size == HEADER_LEN == 40


def test_a1_frame_traz_os_pontos_do_decoder_native() -> None:
    bitmap = voxel_bitmap(z_slices=4, density=0.05, seed=1)
    raw = _raw(bitmap, seq=7, ts=1234.5)

    frame = build_frame(raw, decode_points)

    version, flags, header_len, seq, ts, n_points, resolution, ox, oy, oz, reserved = (
        _header(frame)
    )
    expected = LidarDecoder().decode(raw.payload, lidar_metadata(bitmap))["points"]
    assert (version, flags, header_len, reserved) == (1, 0, 40, 0)
    assert (seq, ts) == (7, 1234.5)
    assert n_points == len(expected) > 0
    assert resolution == np.float32(0.05)
    assert (ox, oy, oz) == tuple(np.float32(v) for v in (-3.2, -3.2, -0.5))
    assert len(frame) == 40 + 12 * n_points
    flat = np.frombuffer(frame, dtype=np.dtype("<f4"), offset=HEADER_LEN)
    points = flat.reshape(-1, 3)
    np.testing.assert_allclose(points, expected, rtol=1e-6, atol=1e-5)


def test_a2_sem_voxel_ocupado_frame_tem_so_cabecalho() -> None:
    bitmap = voxel_bitmap(z_slices=1, density=0.0)

    frame = build_frame(_raw(bitmap), decode_points)

    assert _header(frame)[5] == 0
    assert len(frame) == 40


def test_seq_volta_a_zero_depois_do_maximo_u32() -> None:
    frame = build_frame(_raw(voxel_bitmap(density=0.0), seq=2**32), decode_points)

    assert _header(frame)[3] == 0
