"""Payloads sintéticos de estado, com os campos dos exemplos do legion (F-004).

`lowstate.py`, `sportmodestate.py` e `multiplestate.py` do repositório
`legion1581/unitree_webrtc_connect`. Os valores são inventados e os formatos
não foram vistos no robô.
"""

import json
from typing import Any


def low_state(**overrides: Any) -> dict[str, Any]:
    """`rt/lf/lowstate` com bateria, motores e temperatura."""
    payload: dict[str, Any] = {
        "bms_state": {
            "soc": 87,
            "current": -1500,
            "cycle": 12,
            "bq_ntc": 30,
            "mcu_ntc": 32,
        },
        "power_v": 28.5,
        "temperature_ntc1": 41,
        "motor_state": [
            {"q": 0.1, "temperature": 35, "lost": 0},
            {"q": -0.2, "temperature": 36.5, "lost": 2},
        ],
    }
    payload.update(overrides)
    return payload


def sport_state(**overrides: Any) -> dict[str, Any]:
    """`rt/sportmodestate` com IMU e movimento."""
    payload: dict[str, Any] = {
        "mode": 1,
        "progress": 0.5,
        "gait_type": 1,
        "body_height": 0.32,
        "foot_raise_height": 0.09,
        "position": [1.0, 2.0, 0.3],
        "velocity": [0.1, 0.0, 0.0],
        "yaw_speed": 0.05,
        "range_obstacle": [1.5, 2.0, 0.8, 3.0],
        "foot_force": [100, 110, 95, 105],
        "imu_state": {
            "rpy": [0.01, -0.02, 1.57],
            "quaternion": [1.0, 0.0, 0.0, 0.0],
            "gyroscope": [0.0, 0.1, 0.0],
            "accelerometer": [0.0, 0.0, 9.8],
            "temperature": 40,
        },
    }
    payload.update(overrides)
    return payload


def multiple_state_dict(**overrides: Any) -> dict[str, Any]:
    """Conteúdo de `rt/multiplestate`, ainda como `dict`."""
    payload: dict[str, Any] = {
        "bodyHeight": 0.32,
        "brightness": 5,
        "footRaiseHeight": 0.09,
        "obstaclesAvoidSwitch": True,
        "speedLevel": 1,
        "uwbSwitch": 0,
        "volume": 7,
    }
    payload.update(overrides)
    return payload


def multiple_state(**overrides: Any) -> str:
    """`rt/multiplestate` como chega (exemplo): `data` em string JSON."""
    return json.dumps(multiple_state_dict(**overrides))
