"""`GET /capabilities` — os comandos que a API aceita hoje.

É a fonte única para os consumidores (ex.: o Sense) validarem seus
mapeamentos. A lista é montada a partir das mesmas definições que as rotas de
comando usam (enums e modelos de corpo), para não divergir do que elas aceitam.

`stop` e `damp` são entradas diferentes de propósito: `stop` (`StopMove`) para
de andar e o robô continua de pé; `damp` (`Damp`) desliga a força dos motores.
"""

import hashlib
import json

from fastapi import APIRouter
from pydantic import BaseModel

from app.requests import (
    GestureRequest,
    MoveRequest,
    PostureRequest,
    SpeedLevelRequest,
)
from app.responses import CapabilitiesResponse, Capability
from app.robot.commands import SportCommand

router = APIRouter(tags=["capabilities"])

# Rotas que recebem `{"cmd": ...}`: cada valor do enum vira um comando.
# (rota, enum que valida o `cmd`, modelo do corpo)
_CMD_SOURCES: tuple[tuple[str, type[SportCommand], type[BaseModel]], ...] = (
    ("/commands/posture", PostureRequest.Posture, PostureRequest),
    ("/commands/gesture", GestureRequest.Gesture, GestureRequest),
)

# Rotas que são, elas mesmas, um comando.
# (nome, método, rota, chave em SPORT_CMD, modelo do corpo ou None)
_ROUTE_SOURCES: tuple[tuple[str, str, str, str, type[BaseModel] | None], ...] = (
    ("move", "POST", "/commands/move", "Move", MoveRequest),
    ("stop", "POST", "/commands/stop", "StopMove", None),
    ("speed", "PUT", "/commands/speed", "SpeedLevel", SpeedLevelRequest),
)

# Um grupo novo de comandos entra numa das duas tuplas acima; daqui para baixo
# nada muda. `params` sai dos campos do modelo, não é escrito à mão.
_ALL_SOURCES = [
    Capability(
        name=cmd.value,
        method="POST",
        endpoint=endpoint,
        sport_cmd=cmd.sport_cmd,
        params=list(body.model_fields),
    )
    for endpoint, enum, body in _CMD_SOURCES
    for cmd in enum
] + [
    Capability(
        name=name,
        method=method,
        endpoint=endpoint,
        sport_cmd=sport_cmd,
        params=list(body.model_fields) if body else [],
    )
    for name, method, endpoint, sport_cmd, body in _ROUTE_SOURCES
]

# sha256 e não `hash()`: o `hash()` do Python muda a cada execução. A lista é
# fixa enquanto o processo roda, então o hash é calculado uma vez só.
_VERSION = hashlib.sha256(
    json.dumps([cmd.model_dump() for cmd in _ALL_SOURCES], sort_keys=True).encode()
).hexdigest()[:12]


@router.get(
    "/capabilities",
    response_model=CapabilitiesResponse,
    summary="Comandos disponíveis",
)
async def get_capabilities() -> CapabilitiesResponse:
    """Não depende do robô: responde igual com ele ligado ou desligado."""
    return CapabilitiesResponse(version=_VERSION, commands=_ALL_SOURCES)
