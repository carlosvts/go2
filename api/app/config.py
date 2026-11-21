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
    """Teto para comandos que esperam resposta do robô (os `GET` de velocidade e
    de desvio de obstáculo).
    A lib não impõe timeout nenhum por conta própria."""

    move_rate_hz: float = Field(default=30.0, ge=20.0, le=50.0)
    """Frequência de reenvio interno do comando `Move` (faixa 20–50Hz)."""

    move_max_duration_s: float = Field(default=10.0, gt=0, le=300.0)
    """Janela máxima aceita em `POST /commands/move`."""

    # ─── LiDAR (/ws/lidar, F-001) ──────────────────────────────────────────
    lidar_max_clients: int = Field(default=1, ge=0)
    """Clientes simultâneos em `/ws/lidar`. Acima disso o novo leva `1013`;
    `0` desliga a rota."""

    lidar_client_queue: int = Field(default=2, ge=1)
    """Frames binários à espera por cliente; cheia, descarta o mais antigo."""

    lidar_decode_queue: int = Field(default=2, ge=1)
    """Mensagens do robô à espera do decoder; cheia, descarta a mais antiga."""

    # ─── Telemetria do LiDAR (/ws/telemetry, F-002) ───────────────────────
    telemetry_max_clients: int = Field(default=1, ge=0)
    """Clientes simultâneos em `/ws/telemetry`. Acima disso o novo leva `1013`;
    `0` desliga a rota."""

    telemetry_client_queue: int = Field(default=16, ge=1)
    """Itens à espera por tópico, por cliente de telemetria; cheia, descarta o
    mais antigo do tópico. Não medido."""

    # ─── Vídeo (/ws/video, F-003) ─────────────────────────────────────────
    video_max_clients: int = Field(default=2, ge=0)
    """Clientes simultâneos em `/ws/video`. Acima disso o novo leva `1013`;
    `0` desliga a rota."""

    video_client_queue: int = Field(default=1, ge=1)
    """Frames JPEG à espera por cliente; cheia, descarta o mais antigo."""

    video_encode_queue: int = Field(default=1, ge=1)
    """Quadros à espera do codificador JPEG; cheia, descarta o mais antigo."""

    video_max_fps: float = Field(default=0.0, ge=0)
    """Teto de quadros admitidos por segundo; `0` = sem teto. Padrão a decidir
    depois de medir a taxa da câmera (F-003 H1)."""

    video_jpeg_quality: int = Field(default=80, ge=1, le=100)
    """Qualidade do JPEG. Sugerido, sem medida (F-003 H1)."""

    video_stall_s: float = Field(default=3.0, gt=0)
    """Segundos sem quadro, com a câmera ligada, até o estado `stalled`."""

    # ─── Dispositivo: lanterna, LED, volume (/device/*, F-005) ─────────────
    max_volume: int = Field(default=10, ge=0, le=10)
    """Teto do volume aceito em `PUT /device/volume` (0–10). `10` = sem teto.
    Só limita o que passa pela api."""

    max_brightness: int = Field(default=10, ge=0, le=10)
    """Teto do brilho da lanterna aceito em `PUT /device/brightness` (0–10).
    `10` = sem teto. Só limita o que passa pela api."""

    led_max_duration_s: int = Field(default=60, ge=1)
    """Duração máxima de uma cor em `PUT /device/led`. Sugerido, sem medida: o
    limite do robô não é conhecido."""
    # ─── Estado (/ws/state, F-004) ────────────────────────────────────────
    state_max_clients: int = Field(default=4, ge=0)
    """Clientes simultâneos em `/ws/state`. Acima disso o novo leva `1013`;
    `0` desliga a rota. Sugerido, sem medida (F-004)."""

    state_max_hz: float = Field(default=10.0, ge=0)
    """Teto de frames por segundo, por cliente e por tópico de seção, no
    `/ws/state`; `0` = sem teto. Sugerido, sem medida (F-004 A11)."""

    # ─── Áudio (/speaker/*, F-007) ─────────────────────────────────────────
    audio_max_upload_mb: float = Field(default=5.0, gt=0)
    """Tamanho máximo de um upload de áudio, em MiB. Acima disso, `413` (a
    leitura para no limite). O mesmo limite vale para a F-006."""

    max_vx: float = Field(default=1.0, gt=0)
    """Teto de velocidade frontal aceito em `POST /commands/move`, em m/s."""

    max_vy: float = Field(default=1.0, gt=0)
    """Teto de velocidade lateral aceito em `POST /commands/move`, em m/s."""

    max_vyaw: float = Field(default=2.0, gt=0)
    """Teto de velocidade angular aceito em `POST /commands/move`, em rad/s."""

    @property
    def audio_max_upload_bytes(self) -> int:
        """`audio_max_upload_mb` em bytes (MiB × 1024²)."""
        return int(self.audio_max_upload_mb * 1024 * 1024)

    @model_validator(mode="after")
    def _check_target(self) -> Self:
        """Exige IP ou serial quando o modo é `LocalSTA`."""
        if self.connection_method is ConnectionMethod.local_sta and not (
            self.robot_ip or self.robot_serial_number
        ):
            msg = "LocalSTA exige GO2_ROBOT_IP ou GO2_ROBOT_SERIAL_NUMBER definido."
            raise ValueError(msg)
        return self
