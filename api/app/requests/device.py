"""Corpos de `PUT /device/brightness`, `/device/volume` e `/device/led` (F-005)."""

from pydantic import BaseModel, Field, StrictInt

from app.exceptions import InvalidCommandError
from app.robot.device import LedColor, LedCommand

# Faixa do exemplo `vui.py` (inferido); os tetos do `.env` não passam disso.
MAX_DEVICE_LEVEL = 10


class DeviceLevelRequest(BaseModel):
    """Nível de brilho ou de volume. Modo estrito: `true` e `5.0` levam `422`.

    Este modelo valida a faixa fixa 0–10. O teto configurável
    (`GO2_MAX_BRIGHTNESS`, `GO2_MAX_VOLUME`) é aplicado por :meth:`within`.
    """

    level: StrictInt = Field(
        ge=0, le=MAX_DEVICE_LEVEL, description="Nível de 0 ao teto configurado."
    )

    def within(self, ceiling: int, setting: str) -> int:
        """Devolve o nível, se não passar de `ceiling`.

        Raises:
            InvalidCommandError: acima do teto (vira `422`).
        """
        if self.level > ceiling:
            msg = f"level={self.level} acima do teto {setting}={ceiling}."
            raise InvalidCommandError(msg)
        return self.level


class LedRequest(BaseModel):
    """Cor do LED por `duration_s` segundos; com `flash_cycle_ms`, pisca.

    Modo estrito nos inteiros. O teto `GO2_LED_MAX_DURATION_S` e o limite do
    pisca (`499 ≤ flash_cycle_ms ≤ duration_s × 1000`) são aplicados por
    :meth:`to_command`.
    """

    color: LedColor = Field(description="Cor do LED (`VUI_COLOR` da lib).")
    duration_s: StrictInt = Field(
        ge=1, description="Segundos com a cor, até `GO2_LED_MAX_DURATION_S`."
    )
    flash_cycle_ms: StrictInt | None = Field(
        default=None,
        description=(
            "Período do pisca, em ms, de 499 a `duration_s × 1000` (inferido "
            "do exemplo da lib). Sem ele, a cor fica fixa."
        ),
    )

    def to_command(self, max_duration_s: int) -> LedCommand:
        """Converte para o comando de domínio, validando os limites.

        Raises:
            InvalidCommandError: fora dos limites (vira `422`).
        """
        return LedCommand(
            color=self.color,
            duration_s=self.duration_s,
            flash_cycle_ms=self.flash_cycle_ms,
            max_duration_s=max_duration_s,
        )
