"""Resposta de `GET /status`.

As seções (F-004) vêm dos exemplos do legion e **não foram vistas no robô**:
nomes, tipos e unidades são `inferido`. Campo ilegível vira `null` sozinho.
"""

from datetime import datetime
from typing import Any, Self

from pydantic import BaseModel, Field

from app.robot.connection import ConnectionState
from app.robot.state import RobotStatus

Number = int | float
"""Número sem tipo fixo nos exemplos; repassado como chegou."""


class BatteryTemperatures(BaseModel):
    """Temperaturas do BMS, em °C (`inferido`)."""

    bq: int | None = Field(default=None, description="← `bms_state.bq_ntc`.")
    mcu: int | None = Field(default=None, description="← `bms_state.mcu_ntc`.")


class BatterySection(BaseModel):
    """Bateria, de `rt/lf/lowstate`."""

    percent: int | None = Field(
        default=None,
        description="Carga em %. Mesma extração de `battery_percent`.",
    )
    voltage_v: float | None = Field(default=None, description="← `power_v` (V).")
    current_ma: int | None = Field(
        default=None, description="← `bms_state.current` (mA)."
    )
    cycles: int | None = Field(default=None, description="← `bms_state.cycle`.")
    temperatures_c: BatteryTemperatures = Field(default_factory=BatteryTemperatures)


class ImuSection(BaseModel):
    """IMU, de `rt/sportmodestate` → `imu_state` (radianos, m/s², °C)."""

    rpy: list[float] | None = Field(default=None, description="3 valores.")
    quaternion: list[float] | None = Field(default=None, description="4 valores.")
    gyroscope: list[float] | None = Field(default=None, description="3 valores.")
    accelerometer: list[float] | None = Field(default=None, description="3 valores.")
    temperature: Number | None = None


class MotionSection(BaseModel):
    """Movimento, de `rt/sportmodestate` (metros, m/s, rad/s)."""

    mode: int | None = Field(default=None, description="Mesma extração de `mode`.")
    progress: float | None = None
    gait_type: int | None = None
    body_height: float | None = None
    foot_raise_height: float | None = None
    position: list[float] | None = Field(default=None, description="3 valores.")
    velocity: list[float] | None = Field(default=None, description="3 valores.")
    yaw_speed: float | None = None
    range_obstacle: list[float] | None = Field(
        default=None,
        description="Tamanho livre. Pelo nome, distância ao obstáculo por "
        "direção (não confirmado).",
    )
    foot_force: list[Number] | None = Field(default=None, description="Tamanho livre.")


class MotorItem(BaseModel):
    """Um motor, na ordem de `motor_state`."""

    q: float | None = Field(default=None, description="Posição (rad).")
    temperature_c: Number | None = Field(default=None, description="← `temperature`.")
    lost: int | None = None


class SettingsSection(BaseModel):
    """Configurações, de `rt/multiplestate` (string JSON decodificada)."""

    body_height: float | None = Field(default=None, description="← `bodyHeight`.")
    brightness: Number | None = None
    foot_raise_height: float | None = Field(
        default=None, description="← `footRaiseHeight`."
    )
    obstacle_avoidance: bool | None = Field(
        default=None,
        description="← `obstaclesAvoidSwitch` (0/1 viram bool). Só informativo: "
        "a fonte de verdade é `/safety/obstacle-avoidance`.",
    )
    speed_level: Number | None = Field(default=None, description="← `speedLevel`.")
    uwb: bool | None = Field(default=None, description="← `uwbSwitch`.")
    volume: Number | None = None


class ActiveErrorItem(BaseModel):
    """Erro ativo, do data channel (`[timestamp, source, code]`)."""

    source: int
    source_text: str = Field(description='Texto da lib, ou `"{source}"`.')
    code: int
    code_hex: str = Field(description='Hex maiúsculo, sem `0x` (16 → `"10"`).')
    code_text: str = Field(description='Texto da lib, ou `"{source}-{code_hex}"`.')
    robot_ts: Number | None = Field(description="Timestamp cru do robô.")
    seen_at: float = Field(description="Unix (s) da api quando o erro entrou.")


class StatusResponse(BaseModel):
    """Snapshot do estado do robô, lido do cache."""

    connected: bool = Field(
        description="Há conexão WebRTC viva e canal de dados validado. É o que "
        "decide se os comandos são aceitos ou levam `503`."
    )
    state: ConnectionState = Field(
        description="Estado publicado da conexão. `reconnecting`: a conexão "
        "caiu e a API está tentando de novo, sozinha."
    )
    since: datetime = Field(description="Momento (UTC) da última transição de `state`.")
    battery_percent: int | None = Field(
        default=None,
        description="Carga em %, do cache de `rt/lf/lowstate`. `null` se ainda "
        "não chegou estado ou se o campo não foi reconhecido.",
    )
    mode: int | None = Field(
        default=None, description="Modo atual, do cache de `rt/sportmodestate`."
    )
    sport_state_age_s: float | None = Field(
        default=None,
        description="Há quantos segundos chegou o último `rt/sportmodestate`.",
    )
    low_state_age_s: float | None = Field(
        default=None,
        description="Há quantos segundos chegou o último `rt/lf/lowstate`.",
    )
    multiple_state_age_s: float | None = Field(
        default=None,
        description="Há quantos segundos chegou o último `rt/multiplestate`.",
    )
    battery: BatterySection | None = Field(
        default=None,
        description="`null` se `rt/lf/lowstate` não chegou nesta execução. "
        "Na queda, mantém o último valor (veja a idade e `connected`).",
    )
    imu: ImuSection | None = Field(
        default=None, description="`null` se `rt/sportmodestate` não chegou."
    )
    motion: MotionSection | None = Field(
        default=None, description="`null` se `rt/sportmodestate` não chegou."
    )
    motors: list[MotorItem | None] | None = Field(
        default=None,
        description="Um item por motor; item malformado vira `null`.",
    )
    body_temperature_c: Number | None = Field(
        default=None, description="← `temperature_ntc1` de `rt/lf/lowstate`."
    )
    settings: SettingsSection | None = Field(
        default=None,
        description="`null` se `rt/multiplestate` não chegou ou não é JSON.",
    )
    errors: list[ActiveErrorItem] | None = Field(
        default=None,
        description="Erros ativos do data channel. `null` = **desconhecido** "
        '(nenhuma mensagem nesta conexão, ou a conexão caiu), nunca "sem '
        'erros". `[]` só depois de uma fotografia vazia ou de um `rm_error` '
        "que esvaziou a lista.",
    )
    raw: dict[str, Any] | None = Field(
        default=None,
        description="Payloads crus em cache (`multiple_state` já decodificado). "
        "Presente para permitir fixar a extração na validação com o robô ligado.",
    )

    @classmethod
    def from_status(cls, status: RobotStatus, raw: dict[str, Any] | None) -> Self:
        """Converte o snapshot de domínio na resposta HTTP.

        Args:
            status: Snapshot lido do cache.
            raw: Payloads crus, ou `None` para omiti-los.
        """
        return cls.model_validate(
            {
                "connected": status.connected,
                "state": status.state,
                "since": status.since,
                "battery_percent": status.battery_percent,
                "mode": status.mode,
                "sport_state_age_s": status.sport_state_age_s,
                "low_state_age_s": status.low_state_age_s,
                "multiple_state_age_s": status.multiple_state_age_s,
                "battery": status.battery,
                "imu": status.imu,
                "motion": status.motion,
                "motors": status.motors,
                "body_temperature_c": status.body_temperature_c,
                "settings": status.settings,
                "errors": status.errors,
                "raw": raw,
            }
        )
