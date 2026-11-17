"""Única fronteira com a lib `unitree_webrtc_connect`.

Concentrar os imports da lib aqui (padrão *Anti-Corruption Layer*) deixa o
resto do projeto livre de detalhes dela: se a lib mudar, só este módulo muda.
"""

from collections.abc import Sequence
from typing import Any, ClassVar

import numpy as np
from numpy.typing import NDArray
from unitree_webrtc_connect import (
    DATA_CHANNEL_TYPE,
    OBSTACLES_AVOID_API,
    RTC_TOPIC,
    SPORT_CMD,
    UnitreeWebRTCConnection,
    WebRTCConnectionMethod,
)
from unitree_webrtc_connect.lidar.lidar_decoder_native import (
    LidarDecoder as _NativeLidarDecoder,
)

from app.config import ConnectionMethod, Settings
from app.robot.ports import WebRTCConnection

__all__ = [
    "DATA_CHANNEL_TYPE",
    "OBSTACLES_AVOID_API",
    "RTC_TOPIC",
    "SPORT_CMD",
    "RawLidarDecoder",
    "UnitreeConnectionFactory",
    "decode_points",
    "install_raw_lidar_decoder",
]

_NATIVE_DECODER = _NativeLidarDecoder()


class RawLidarDecoder:
    """Decoder de repasse: não descomprime nada (F-001).

    A lib chama `datachannel.decoder.decode(binário, metadados)` dentro do
    handler do data channel, na thread do event loop, e põe o retorno em
    `message["data"]["data"]`. Com este decoder instalado, o callback recebe
    os bytes ainda comprimidos e a api decodifica fora do loop.
    """

    def decode(self, compressed_data: bytes, metadata: object) -> bytes:
        """Devolve os bytes comprimidos, sem tocar neles."""
        return bytes(compressed_data)

    def get_decoder_name(self) -> str:
        """Nome exibido pela lib, por simetria com `UnifiedLidarDecoder`."""
        return "RawLidarDecoder"


def install_raw_lidar_decoder(datachannel: Any) -> None:  # noqa: ANN401
    """Troca o decoder do data channel pelo de repasse.

    O data channel é recriado a cada `connect()` da lib, então isto precisa
    ser refeito a cada conexão.
    """
    datachannel.decoder = RawLidarDecoder()


def decode_points(
    payload: bytes,
    src_size: int,
    origin: Sequence[float],
    resolution: float,
) -> NDArray[np.float64]:
    """Decodifica o voxel map comprimido em pontos `(N, 3)`, em metros.

    Usa o decoder `native` da lib (lz4 + numpy). Pesa na CPU: chame fora da
    thread do event loop.
    """
    result = _NATIVE_DECODER.decode(
        payload,
        {"src_size": src_size, "origin": list(origin), "resolution": resolution},
    )
    points: NDArray[np.float64] = np.asarray(result["points"], dtype=np.float64)
    return points


class UnitreeConnectionFactory:
    """Cria a `UnitreeWebRTCConnection` correspondente à configuração."""

    _METHODS: ClassVar[dict[ConnectionMethod, Any]] = {
        ConnectionMethod.local_sta: WebRTCConnectionMethod.LocalSTA,
        ConnectionMethod.local_ap: WebRTCConnectionMethod.LocalAP,
    }

    def __init__(self, settings: Settings) -> None:
        """Guarda a configuração usada em cada conexão criada."""
        self._settings = settings

    def __call__(self) -> WebRTCConnection:
        """Devolve uma conexão nova, ainda fechada.

        Firmware anterior a 1.1.15 não exige chave por dispositivo (dossiê
        7.3). Se o firmware for atualizado, passe também
        `aes_128_key=self._settings.robot_aes_128_key`.
        """
        settings = self._settings
        connection: WebRTCConnection = UnitreeWebRTCConnection(
            self._METHODS[settings.connection_method],
            ip=settings.robot_ip,
            serialNumber=settings.robot_serial_number,
        )
        return connection
