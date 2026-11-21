"""Única fronteira com a lib `unitree_webrtc_connect`.

Concentrar os imports da lib aqui (padrão *Anti-Corruption Layer*) deixa o
resto do projeto livre de detalhes dela: se a lib mudar, só este módulo muda.
"""

import logging
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
from unitree_webrtc_connect.constants import VUI_COLOR
from unitree_webrtc_connect.lidar.lidar_decoder_native import (
    LidarDecoder as _NativeLidarDecoder,
)
from unitree_webrtc_connect.msgs.error_handler import (
    get_error_code_text,
    get_error_source_text,
    integer_to_hex_string,
)

from app.config import ConnectionMethod, Settings
from app.robot.ports import (
    DataChannelMessageListener,
    VideoTrackListener,
    WebRTCConnection,
)

__all__ = [
    "DATA_CHANNEL_TYPE",
    "OBSTACLES_AVOID_API",
    "RTC_TOPIC",
    "SPORT_CMD",
    "VUI_COLOR",
    "RawLidarDecoder",
    "UnitreeConnectionFactory",
    "VideoHookedConnection",
    "decode_points",
    "describe_error",
    "install_raw_lidar_decoder",
]

log = logging.getLogger(__name__)

_NATIVE_DECODER = _NativeLidarDecoder()

_ERROR_MESSAGE_TYPES = frozenset(
    {
        DATA_CHANNEL_TYPE["ERRORS"],
        DATA_CHANNEL_TYPE["ADD_ERROR"],
        DATA_CHANNEL_TYPE["RM_ERROR"],
    }
)
"""Tipos de mensagem do data channel que a lib só imprime (F-004)."""


def describe_error(source: int, code: int) -> tuple[str, str, str]:
    """Textos de um erro do robô, com as funções e a tabela da lib.

    Returns:
        `(source_text, code_hex, code_text)`. `code_hex` é hex maiúsculo,
        sem `0x` (16 → `"10"`); sem texto na tabela, os fallbacks da lib:
        `"{source}"` e `"{source}-{code_hex}"`.
    """
    code_hex = str(integer_to_hex_string(code))
    return (
        str(get_error_source_text(source)),
        code_hex,
        str(get_error_code_text(source, code_hex)),
    )


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


class VideoHookedConnection(UnitreeWebRTCConnection):  # type: ignore[misc]
    """Conexão da lib com ganchos para a api, sem patch na lib.

    - Vídeo (F-003): a lib cria `self.video` em `init_webrtc`, já dentro do
      `connect()`, e chama os callbacks dele no evento `track`, antes de o
      `connect()` retornar. A propriedade `video` intercepta a atribuição e
      registra o callback nessa hora, a cada conexão.
    - Erros (F-004): a lib cria `self.datachannel` no mesmo `init_webrtc`. A
      propriedade `datachannel` embrulha o `handle_response` dessa instância:
      o original roda e, depois, as mensagens `errors`/`add_error`/`rm_error`
      vão para :attr:`datachannel_message_listener`. Como o gancho entra na
      criação do canal, a fotografia de erros que chega logo depois da
      validação, ainda dentro do `connect()`, não se perde.
    """

    video_track_listener: VideoTrackListener | None = None
    datachannel_message_listener: DataChannelMessageListener | None = None

    @property
    def datachannel(self) -> Any:  # noqa: ANN401 - `WebRTCDataChannel` da lib
        """Data channel da lib, criado a cada `connect()`."""
        return self.__dict__.get("_datachannel")

    @datachannel.setter
    def datachannel(self, channel: Any) -> None:  # noqa: ANN401
        self.__dict__["_datachannel"] = channel
        original = channel.handle_response

        async def handle_response(message: Any) -> None:  # noqa: ANN401
            try:
                await original(message)
            finally:
                self._deliver_datachannel_message(channel, message)

        channel.handle_response = handle_response

    def _deliver_datachannel_message(self, channel: Any, message: Any) -> None:  # noqa: ANN401
        """Entrega as mensagens de erro; falha da api fica no log, longe da lib."""
        listener = self.datachannel_message_listener
        if listener is None or not isinstance(message, dict):
            return
        if message.get("type") not in _ERROR_MESSAGE_TYPES:
            return
        try:
            listener(channel, message)
        except Exception:
            log.exception("❌ Falha ao tratar mensagem de erro do data channel.")

    @property
    def video(self) -> Any:  # noqa: ANN401 - `WebRTCVideoChannel` da lib
        """Canal de vídeo da lib, criado a cada `connect()`."""
        return self.__dict__.get("_video_channel")

    @video.setter
    def video(self, channel: Any) -> None:  # noqa: ANN401
        self.__dict__["_video_channel"] = channel
        channel.add_track_callback(self._deliver_video_track)

    async def _deliver_video_track(self, track: Any) -> None:  # noqa: ANN401
        """Entrega a track e retorna logo: a lib espera cada callback em ordem."""
        listener = self.video_track_listener
        if listener is not None:
            listener(track)


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
        connection: WebRTCConnection = VideoHookedConnection(
            self._METHODS[settings.connection_method],
            ip=settings.robot_ip,
            serialNumber=settings.robot_serial_number,
        )
        return connection
