"""`GET /status` — snapshot pontual do cache de estado."""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.dependencies import RobotDep
from app.models import StatusResponse

router = APIRouter(tags=["status"])


@router.get("/status", response_model=StatusResponse, summary="Estado do robô")
async def get_status(
    robot: RobotDep,
    raw: bool = Query(
        default=False,
        description="Inclui os payloads crus de estado, sem interpretação.",
    ),
) -> StatusResponse:
    """Lê do cache alimentado pelas assinaturas feitas na conexão — não gera
    tráfego novo com o robô.

    Responde `200` mesmo com o robô desligado: nesse caso `connected` vem
    `false`. É este endpoint que diferencia "robô fora do ar" de "API fora do
    ar", então ele nunca devolve `503`.
    """
    snapshot = robot.status()
    return StatusResponse(
        connected=snapshot.connected,
        battery_percent=snapshot.battery_percent,
        mode=snapshot.mode,
        sport_state_age_s=snapshot.sport_state_age_s,
        low_state_age_s=snapshot.low_state_age_s,
        raw=robot.raw_state if raw else None,
    )
