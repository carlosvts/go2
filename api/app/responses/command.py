"""Resposta padrão dos comandos."""

from pydantic import BaseModel, Field


class CommandAccepted(BaseModel):
    """Resposta de `202 Accepted`.

    A API confirma que aceitou e despachou o comando — não que o robô terminou
    de executá-lo fisicamente (`docs/arquitetura_go2_api.md` seção 2).
    """

    cmd: str = Field(
        description=(
            "Nome do comando despachado: a chave em `SPORT_CMD` ou, fora dos "
            "comandos esportivos, o nome do recurso (`ObstacleAvoidance`)."
        )
    )
    accepted: bool = True
