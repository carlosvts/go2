"""`GET /status` — snapshot pontual do cache de estado."""

from fastapi import APIRouter, Query

from app.dependencies import RobotDep
from app.responses import StatusResponse

router = APIRouter(tags=["status"])


@router.get("/status", response_model=StatusResponse, summary="Estado do robô")
async def get_status(
    robot: RobotDep,
    raw: bool = Query(
        default=False,
        description="Inclui os payloads crus de estado, sem interpretação.",
    ),
) -> StatusResponse:
    """Lê do cache alimentado pelas assinaturas feitas na conexão.

    Não gera tráfego novo com o robô. Responde `200` mesmo com o robô
    desligado: nesse caso `connected` vem `false`. É este endpoint que
    diferencia "robô fora do ar" de "API fora do ar", então ele nunca devolve
    `503`.
    """
    return StatusResponse.from_status(robot.status(), robot.raw_state if raw else None)
