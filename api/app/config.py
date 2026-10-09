"""Configuração da go2-api, carregada de variáveis de ambiente / `.env`.

Todas as chaves usam o prefixo `GO2_` (ver `.env.example`).
"""

from enum import StrEnum
from typing import Self

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ConnectionMethod(StrEnum):
    """Modos de conexão suportados nesta versão.

    `Remote` (STA-T, túnel pela nuvem da Unitree) é deliberadamente deixado de
    fora: exige conta cadastrada e internet.
    Ver `docs/go2_modelo_mental.md` seção 3.
    """

    local_sta = "LocalSTA"
    local_ap = "LocalAP"


class Settings(BaseSettings):
    """Configuração imutável e validada na construção.

    Combinações inválidas (por exemplo, `LocalSTA` sem IP nem serial) impedem
    a criação do objeto: a API falha ao subir, não no primeiro comando.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="GO2_",
        extra="ignore",
        frozen=True,
    )

    # ─── Conexão com o robô ────────────────────────────────────────────────
    connection_method: ConnectionMethod = ConnectionMethod.local_sta

    robot_ip: str | None = None
    """IP do robô na rede externa (a de um roteador, por ex).

    Atenção: NÃO é um endereço `192.168.123.x` — essa é a rede interna do robô,
    alcançável só por cabo e inexistente num Pro. Ver `docs/go2_modelo_mental.md`
    seção 3.
    """

    robot_serial_number: str | None = None
    """Serial do robô (ex: `B42D...`). Alternativa ao IP em LocalSTA: a lib
    encontra o robô por descoberta multicast, o que é imune à troca de IP pelo
    DHCP do roteador."""

    # O firmware deste robô é anterior a 1.1.15 e não exige chave AES-128 por
    # dispositivo (dossiê seção 7.3), então este campo fica preparado mas NÃO é
    # repassado à lib. Se o firmware for atualizado, basta preencher e passar
    # `aes_128_key=` em `app.robot.unitree.UnitreeConnectionFactory`.
    robot_aes_128_key: str | None = None

    connect_on_startup: bool = True
    """Se falso, a API sobe sem tentar conectar (útil para testes sem robô)."""

    reconnect_interval_s: float = Field(default=5.0, gt=0)
    """Intervalo entre as verificações da conexão. Se ela caiu, cada verificação
    é também uma tentativa de reconectar. Ver `Go2Robot.keep_connected`."""

    # ─── Comportamento de comando ──────────────────────────────────────────
    request_timeout_s: float = Field(default=5.0, gt=0)
    """Teto para comandos que esperam resposta do robô (só `GET /commands/speed`).
    A lib não impõe timeout nenhum por conta própria."""

    move_rate_hz: float = Field(default=30.0, ge=20.0, le=50.0)
    """Frequência de reenvio interno do comando `Move` (faixa 20–50Hz)."""

    move_max_duration_s: float = Field(default=10.0, gt=0, le=300.0)
    """Janela máxima aceita em `POST /commands/move`."""

    max_vx: float = Field(default=1.0, gt=0)
    """Teto de velocidade frontal aceito em `POST /commands/move`, em m/s."""

    max_vy: float = Field(default=1.0, gt=0)
    """Teto de velocidade lateral aceito em `POST /commands/move`, em m/s."""

    max_vyaw: float = Field(default=2.0, gt=0)
    """Teto de velocidade angular aceito em `POST /commands/move`, em rad/s."""

    @model_validator(mode="after")
    def _check_target(self) -> Self:
        """Exige IP ou serial quando o modo é `LocalSTA`."""
        if self.connection_method is ConnectionMethod.local_sta and not (
            self.robot_ip or self.robot_serial_number
        ):
            msg = "LocalSTA exige GO2_ROBOT_IP ou GO2_ROBOT_SERIAL_NUMBER definido."
            raise ValueError(msg)
        return self
