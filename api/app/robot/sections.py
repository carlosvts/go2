"""Extração das seções de estado do `/status` e do `/ws/state` (F-004).

Os nomes vêm dos exemplos `lowstate.py`, `sportmodestate.py` e
`multiplestate.py` do repositório do legion e não foram vistos no robô.
Regra geral: campo ausente, de tipo diferente do esperado ou não finito vira
`None` sozinho; `bool` não conta como número. Nada é convertido além de
renomear (e `int` → `float` nos campos `float`).
"""

import math
from collections.abc import Callable
from typing import Any, ClassVar

from app.robot.payload import PayloadReader

Section = dict[str, Any]
"""Seção já pronta para JSON estrito (sem `NaN`)."""

_FLAG_INTS = (0, 1)


def _int(value: object) -> int | None:
    """Inteiro que não é `bool`."""
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return None


def _number(value: object) -> int | float | None:
    """Número finito que não é `bool`, no tipo original."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _float(value: object) -> float | None:
    """Número finito como `float`; inteiro enorme (sem `float`) vira `None`."""
    number = _number(value)
    if number is None:
        return None
    try:
        return float(number)
    except OverflowError:
        return None


def _flag(value: object) -> bool | None:
    """`bool`, ou `0`/`1` como `bool`."""
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in _FLAG_INTS:
        return bool(value)
    return None


def _list[T](
    value: object, item: Callable[[object], T | None], size: int | None = None
) -> list[T] | None:
    """Lista em que todo item é válido; com `size`, de tamanho exato."""
    if not isinstance(value, list | tuple):
        return None
    if size is not None and len(value) != size:
        return None
    items = [item(element) for element in value]
    if any(element is None for element in items):
        return None
    return [element for element in items if element is not None]


def _get(payload: object, *path: str) -> object:
    return PayloadReader.first_path(payload, path)


class StateSections:
    """Extrai cada seção do payload cru do tópico de origem.

    Payload que não é `dict` (tópico que nunca chegou, mensagem sem `data`)
    dá a seção inteira `None`.
    """

    _BATTERY_PATHS: ClassVar[tuple[tuple[str, ...], ...]] = (
        ("bms_state", "soc"),
        ("bms", "soc"),
        ("soc",),
    )
    """Os três caminhos de `battery_percent` (pendentes de validação física)."""

    @classmethod
    def battery_percent(cls, low: object) -> int | None:
        """Carga em %: a mesma extração de `battery_percent` e `battery.percent`."""
        return _int(PayloadReader.first_path(low, *cls._BATTERY_PATHS))

    @staticmethod
    def mode(sport: object) -> int | None:
        """Modo: a mesma extração de `mode` e `motion.mode`."""
        return _int(_get(sport, "mode"))

    @classmethod
    def battery(cls, low: object) -> Section | None:
        """Seção `battery`, de `LOW_STATE`."""
        if not isinstance(low, dict):
            return None
        return {
            "percent": cls.battery_percent(low),
            "voltage_v": _float(low.get("power_v")),
            "current_ma": _int(_get(low, "bms_state", "current")),
            "cycles": _int(_get(low, "bms_state", "cycle")),
            "temperatures_c": {
                "bq": _int(_get(low, "bms_state", "bq_ntc")),
                "mcu": _int(_get(low, "bms_state", "mcu_ntc")),
            },
        }

    @staticmethod
    def imu(sport: object) -> Section | None:
        """Seção `imu`, de `SPORT_MOD_STATE.imu_state`."""
        if not isinstance(sport, dict):
            return None
        imu = sport.get("imu_state")
        return {
            "rpy": _list(_get(imu, "rpy"), _float, 3),
            "quaternion": _list(_get(imu, "quaternion"), _float, 4),
            "gyroscope": _list(_get(imu, "gyroscope"), _float, 3),
            "accelerometer": _list(_get(imu, "accelerometer"), _float, 3),
            "temperature": _number(_get(imu, "temperature")),
        }

    @classmethod
    def motion(cls, sport: object) -> Section | None:
        """Seção `motion`, de `SPORT_MOD_STATE`."""
        if not isinstance(sport, dict):
            return None
        return {
            "mode": cls.mode(sport),
            "progress": _float(sport.get("progress")),
            "gait_type": _int(sport.get("gait_type")),
            "body_height": _float(sport.get("body_height")),
            "foot_raise_height": _float(sport.get("foot_raise_height")),
            "position": _list(sport.get("position"), _float, 3),
            "velocity": _list(sport.get("velocity"), _float, 3),
            "yaw_speed": _float(sport.get("yaw_speed")),
            "range_obstacle": _list(sport.get("range_obstacle"), _float),
            "foot_force": _list(sport.get("foot_force"), _number),
        }

    @staticmethod
    def _motor(item: object) -> Section | None:
        if not isinstance(item, dict):
            return None
        return {
            "q": _float(item.get("q")),
            "temperature_c": _number(item.get("temperature")),
            "lost": _int(item.get("lost")),
        }

    @classmethod
    def motors(cls, low: object) -> list[Section | None] | None:
        """Seção `motors`, na ordem de `LOW_STATE.motor_state`.

        Item que não é objeto vira `None` sem zerar a lista.
        """
        if not isinstance(low, dict):
            return None
        motors = low.get("motor_state")
        if not isinstance(motors, list | tuple):
            return None
        return [cls._motor(item) for item in motors]

    @staticmethod
    def body_temperature_c(low: object) -> int | float | None:
        """Seção `body_temperature_c`, de `LOW_STATE.temperature_ntc1`."""
        if not isinstance(low, dict):
            return None
        return _number(low.get("temperature_ntc1"))

    @staticmethod
    def settings(multiple: object) -> Section | None:
        """Seção `settings`, de `MULTIPLE_STATE` já decodificado."""
        if not isinstance(multiple, dict):
            return None
        return {
            "body_height": _float(multiple.get("bodyHeight")),
            "brightness": _number(multiple.get("brightness")),
            "foot_raise_height": _float(multiple.get("footRaiseHeight")),
            "obstacle_avoidance": _flag(multiple.get("obstaclesAvoidSwitch")),
            "speed_level": _number(multiple.get("speedLevel")),
            "uwb": _flag(multiple.get("uwbSwitch")),
            "volume": _number(multiple.get("volume")),
        }
