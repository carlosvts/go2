"""Única fronteira com a lib `unitree_webrtc_connect`.

Concentrar os imports da lib aqui (padrão *Anti-Corruption Layer*) deixa o
resto do projeto livre de detalhes dela: se a lib mudar, só este módulo muda.
"""

from typing import Any, ClassVar

from unitree_webrtc_connect import (
    DATA_CHANNEL_TYPE,
    RTC_TOPIC,
    SPORT_CMD,
    UnitreeWebRTCConnection,
    WebRTCConnectionMethod,
)

from app.config import ConnectionMethod, Settings
from app.robot.ports import WebRTCConnection

__all__ = [
    "DATA_CHANNEL_TYPE",
    "RTC_TOPIC",
    "SPORT_CMD",
    "UnitreeConnectionFactory",
]


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
