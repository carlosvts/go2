"""Payloads de LiDAR sintéticos, no formato que o robô manda.

O voxel map é um bitmap comprimido com lz4 (bloco, sem tamanho embutido).
Cada byte cobre 8 voxels em x; 16 bytes formam uma linha y; 0x800 bytes formam
uma fatia z (ver `lidar_decoder_native.bits_to_points` na lib). Nada aqui foi
capturado do robô: tamanhos e densidades são escolhas do teste.
"""

import json
import struct
from typing import Any

import lz4.block
import numpy as np

from app.robot.unitree import RTC_TOPIC

LIDAR_TOPIC = RTC_TOPIC["ULIDAR_ARRAY"]
SLICE_BYTES = 0x800


def voxel_bitmap(*, z_slices: int = 4, density: float = 0.05, seed: int = 0) -> bytes:
    """Bitmap descomprimido com uma fração `density` de bytes não nulos."""
    rng = np.random.default_rng(seed)
    size = z_slices * SLICE_BYTES
    occupied = rng.random(size) < density
    values = rng.integers(1, 256, size=size, dtype=np.uint8)
    return (occupied * values).astype(np.uint8).tobytes()


def compress(bitmap: bytes) -> bytes:
    """Comprime como o robô: lz4 em bloco, sem o tamanho no cabeçalho."""
    return bytes(lz4.block.compress(bitmap, store_size=False))


def lidar_metadata(
    bitmap: bytes,
    *,
    origin: tuple[float, float, float] = (-3.2, -3.2, -0.5),
    resolution: float = 0.05,
) -> dict[str, Any]:
    """Campos do `message["data"]` que o decoder lê."""
    return {"src_size": len(bitmap), "origin": list(origin), "resolution": resolution}


def lidar_message(
    bitmap: bytes,
    *,
    origin: tuple[float, float, float] = (-3.2, -3.2, -0.5),
    resolution: float = 0.05,
) -> dict[str, Any]:
    """Mensagem como o callback recebe com o decoder de repasse instalado."""
    data = lidar_metadata(bitmap, origin=origin, resolution=resolution)
    data["data"] = compress(bitmap)
    return {"type": "msg", "topic": LIDAR_TOPIC, "data": data}


def lib_lidar_buffer(bitmap: bytes, **kwargs: Any) -> bytes:
    """Mensagem binária crua do data channel, no formato que a lib desmonta.

    `deal_array_buffer`: `<HH` = (2, 0) marca LiDAR; depois `<I` com o
    tamanho do JSON, 4 bytes ignorados, o JSON e o payload comprimido.
    """
    header = {
        "type": "msg",
        "topic": LIDAR_TOPIC,
        "data": lidar_metadata(bitmap, **kwargs),
    }
    encoded = json.dumps(header).encode()
    return (
        struct.pack("<HH", 2, 0)
        + struct.pack("<I", len(encoded))
        + b"\x00" * 4
        + encoded
        + compress(bitmap)
    )
