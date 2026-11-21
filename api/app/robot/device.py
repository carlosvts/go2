"""Lanterna, LED e volume do robô pelo serviço VUI (F-005).

Os api_ids e os payloads vêm do exemplo `vui.py` do repositório da lib, não
das constantes dela, e não foram vistos no robô. O formato da resposta
(`data.header.status.code`, `data.data` como string JSON) também é do exemplo.
"""

import json
from dataclasses import InitVar, dataclass
from enum import StrEnum
from typing import Any

from app.exceptions import InvalidCommandError, RobotRejectedError
from app.robot.channel import VuiChannel
from app.robot.payload import PayloadReader

# `flash_cycle` mínimo, em ms: comentário do exemplo `vui.py` (inferido).
MIN_FLASH_CYCLE_MS = 499


class LedColor(StrEnum):
    """Cores do LED, iguais aos valores de `VUI_COLOR` da lib."""

    white = "white"
    red = "red"
    yellow = "yellow"
    blue = "blue"
    green = "green"
    cyan = "cyan"
    purple = "purple"


@dataclass(frozen=True)
class LedCommand:
    """Cor do LED por um tempo, com pisca opcional, já validada.

    A construção falha com :class:`InvalidCommandError` fora dos limites:
    `1 ≤ duration_s ≤ max_duration_s` e, se houver pisca,
    `499 ≤ flash_cycle_ms ≤ duration_s × 1000`.
    """

    color: LedColor
    duration_s: int
    flash_cycle_ms: int | None
    max_duration_s: InitVar[int]

    def __post_init__(self, max_duration_s: int) -> None:
        """Valida os valores, levantando se houver problema."""
        if not 1 <= self.duration_s <= max_duration_s:
            msg = (
                f"duration_s={self.duration_s} fora de 1..{max_duration_s} "
                f"(teto GO2_LED_MAX_DURATION_S={max_duration_s})."
            )
            raise InvalidCommandError(msg)
        ceiling_ms = self.duration_s * 1000
        flash = self.flash_cycle_ms
        if flash is not None and not MIN_FLASH_CYCLE_MS <= flash <= ceiling_ms:
            msg = (
                f"flash_cycle_ms={flash} fora de "
                f"{MIN_FLASH_CYCLE_MS}..{ceiling_ms} (duration_s × 1000)."
            )
            raise InvalidCommandError(msg)

    @property
    def parameter(self) -> dict[str, Any]:
        """`parameter` do api_id 1007; sem pisca, não manda `flash_cycle`."""
        parameter: dict[str, Any] = {"color": self.color.value, "time": self.duration_s}
        if self.flash_cycle_ms is not None:
            parameter["flash_cycle"] = self.flash_cycle_ms
        return parameter


class VuiResponse:
    """Interpreta as respostas do serviço VUI; o que não bate vira `502`."""

    @staticmethod
    def ensure_accepted(response: object) -> None:
        """Exige `data.header.status.code == 0`.

        Raises:
            RobotRejectedError: código ≠ 0 ou resposta sem `header.status`.
        """
        data = response.get("data") if isinstance(response, dict) else None
        code = PayloadReader.first_path(data, ("header", "status", "code"))
        if code is None:
            msg = "❌ Resposta do robô sem header.status.code."
            raise RobotRejectedError(msg)
        if type(code) is not int or code != 0:
            msg = f"❌ O robô recusou o pedido (código {code})."
            raise RobotRejectedError(msg)

    @classmethod
    def read_level(cls, response: object, field: str) -> int:
        """Exige o aceite e lê o inteiro `field` de `data.data` (string JSON).

        Raises:
            RobotRejectedError: recusa, `data.data` que não é JSON, ou campo
                ausente ou não inteiro.
        """
        cls.ensure_accepted(response)
        data = response.get("data") if isinstance(response, dict) else None
        raw = data.get("data") if isinstance(data, dict) else None
        if not isinstance(raw, str):
            msg = "❌ Resposta do robô sem data.data em texto."
            raise RobotRejectedError(msg)
        try:
            decoded = json.loads(raw)
        except ValueError as exc:
            msg = "❌ data.data da resposta do robô não é JSON."
            raise RobotRejectedError(msg) from exc
        value = decoded.get(field) if isinstance(decoded, dict) else None
        if type(value) is not int:
            msg = f"❌ Resposta do robô sem o campo inteiro {field!r} em data.data."
            raise RobotRejectedError(msg)
        return value


class DeviceControls:
    """Lanterna (brilho), LED (cor) e volume, sempre esperando o aceite.

    Cada pedido aguarda a própria resposta, com timeout; não toca no
    movimento, então `stop` segue respondendo durante a espera.
    """

    def __init__(self, channel: VuiChannel) -> None:
        """Recebe o canal VUI."""
        self._channel = channel

    async def set_brightness(self, level: int) -> None:
        """Define o brilho da lanterna (1005)."""
        response = await self._channel.request("SetBrightness", {"brightness": level})
        VuiResponse.ensure_accepted(response)

    async def get_brightness(self) -> int:
        """Lê o brilho da lanterna (1006)."""
        response = await self._channel.request("GetBrightness")
        return VuiResponse.read_level(response, "brightness")

    async def set_volume(self, level: int) -> None:
        """Define o volume (1003)."""
        response = await self._channel.request("SetVolume", {"volume": level})
        VuiResponse.ensure_accepted(response)

    async def get_volume(self) -> int:
        """Lê o volume (1004)."""
        response = await self._channel.request("GetVolume")
        return VuiResponse.read_level(response, "volume")

    async def set_led(self, command: LedCommand) -> None:
        """Mostra a cor do LED pelo tempo pedido (1007)."""
        response = await self._channel.request("SetLed", command.parameter)
        VuiResponse.ensure_accepted(response)
