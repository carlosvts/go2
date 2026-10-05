"""Corpo de `POST /commands/move`."""

from pydantic import BaseModel, Field

from app.robot.commands import MoveCommand, MoveLimits


class MoveRequest(BaseModel):
    """Velocidades no referencial do robô.

    Este modelo valida só o que independe da configuração (tipos, números
    finitos, duração positiva). Os tetos configuráveis (`GO2_MAX_VX`,
    `GO2_MAX_VY`, `GO2_MAX_VYAW` e `GO2_MOVE_MAX_DURATION_S`) são aplicados
    por :meth:`to_command`, cujo resultado se recusa a existir fora deles.
    """

    vx: float = Field(
        allow_inf_nan=False, description="Velocidade para frente, em m/s."
    )
    vy: float = Field(allow_inf_nan=False, description="Velocidade lateral, em m/s.")
    vyaw: float = Field(
        allow_inf_nan=False, description="Velocidade angular, em rad/s."
    )
    duration_s: float = Field(
        gt=0,
        allow_inf_nan=False,
        description="Por quanto tempo a API reenvia o comando ao robô.",
    )

    def to_command(self, limits: MoveLimits) -> MoveCommand:
        """Converte para o objeto de domínio, validando contra `limits`.

        Raises:
            InvalidCommandError: se algum teto for excedido.
        """
        return MoveCommand(
            vx=self.vx,
            vy=self.vy,
            vyaw=self.vyaw,
            duration_s=self.duration_s,
            limits=limits,
        )
