"""Interpretação da resposta de `SWITCH_GET` do desvio de obstáculo."""

import json
from dataclasses import dataclass
from typing import Any, ClassVar, Self

from app.robot.payload import PayloadReader


@dataclass(frozen=True)
class ObstacleAvoidanceReading:
    """Se o desvio de obstáculo está ligado, mais a resposta crua."""

    enabled: bool | None
    raw: Any

    # Pendente de validação física: onde, dentro de `data`, está o `enable`.
    _ENABLE_PATHS: ClassVar[tuple[tuple[str, ...], ...]] = (
        ("data", "enable"),
        ("enable",),
        ("data", "enabled"),
        ("enabled",),
    )

    @classmethod
    def from_response(cls, response: object) -> Self:
        """Extrai o `enable` por tentativa; `None` se nenhum caminho bater.

        A resposta vem embrulhada em `data`. O conteúdo de `data.data` pode
        chegar como string JSON (é assim nas respostas esportivas da lib), e
        nesse caso é decodificado antes da busca. O payload cru acompanha o
        resultado para fixar o formato na primeira validação física.
        """
        data = response.get("data") if isinstance(response, dict) else None
        value = PayloadReader.first_path(cls._decoded(data), *cls._ENABLE_PATHS)
        return cls(enabled=value if isinstance(value, bool) else None, raw=data)

    @staticmethod
    def _decoded(data: object) -> object:
        """Cópia de `data` com `data["data"]` decodificado, se for JSON em string."""
        if not isinstance(data, dict) or not isinstance(data.get("data"), str):
            return data
        try:
            return {**data, "data": json.loads(data["data"])}
        except ValueError:
            return data
