"""Corpos de `PATCH /audio/files/{id}` e `PUT /audio/play-mode` (F-006)."""

from pydantic import BaseModel, Field

from app.robot.audio import AudioName, PlayMode


class AudioRenameRequest(BaseModel):
    r"""Nome novo no robô.

    A regra (1–64 caracteres, sem `/`, `\` nem controle) é aplicada por
    :meth:`validated`, depois de tirar os espaços das pontas.
    """

    name: str = Field(description="Nome novo no robô.")

    def validated(self) -> str:
        """Nome sem espaços nas pontas.

        Raises:
            InvalidCommandError: fora da regra (vira `422`).
        """
        return AudioName.validate(self.name)


class PlayModeRequest(BaseModel):
    """Modo de reprodução; outro valor leva `422`."""

    mode: PlayMode
