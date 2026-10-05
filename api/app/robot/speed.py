"""Interpretação da resposta de `GetSpeedLevel`."""

from dataclasses import dataclass
from typing import Any, ClassVar, Self

from app.robot.payload import PayloadReader


@dataclass(frozen=True)
class SpeedReading:
    """Nível de velocidade informado pelo robô, mais a resposta crua."""

    level: int | None
    raw: Any

    # Pendente de validação física: onde, dentro de `data`, está o nível.
    _LEVEL_PATHS: ClassVar[tuple[tuple[str, ...], ...]] = (
        ("data",),
        ("level",),
        ("speed_level",),
    )

    @classmethod
    def from_response(cls, response: Any) -> Self:
        """Extrai o nível por tentativa; `level` é `None` se nenhum caminho bater.

        A resposta vem embrulhada em `data`, igual às mensagens de estado
        (padrão exigido pelo webrtc_bridge). O payload cru acompanha o
        resultado para permitir fixar o formato na primeira validação física.
        """
        data = response.get("data") if isinstance(response, dict) else None
        level = PayloadReader.first_path(data, *cls._LEVEL_PATHS)
        if isinstance(level, str):
            try:
                level = int(level)
            except ValueError:
                level = None
        return cls(level=level if isinstance(level, int) else None, raw=data)
