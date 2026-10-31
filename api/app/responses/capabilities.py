"""Resposta de `GET /capabilities`."""

from pydantic import BaseModel, Field


class Capability(BaseModel):
    """Um comando aceito pela API e como pedi-lo."""

    name: str = Field(
        description="Nome do comando. Nas rotas com `cmd`, é o valor exato dele."
    )
    method: str = Field(description="Método HTTP da rota.")
    endpoint: str = Field(description="Rota que executa o comando.")
    sport_cmd: str = Field(description="Chave correspondente em `SPORT_CMD`.")
    params: list[str] = Field(
        description="Campos do corpo JSON. Lista vazia = rota sem corpo."
    )


class CapabilitiesResponse(BaseModel):
    """Lista dos comandos disponíveis e a versão dela."""

    version: str = Field(
        description="Hash da lista de comandos. Muda se, e só se, a lista mudar."
    )
    commands: list[Capability]
