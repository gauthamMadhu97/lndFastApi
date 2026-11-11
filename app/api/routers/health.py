import logging

from fastapi import APIRouter, Response, status
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.api.deps import AppSettings, DbSession
from app.schemas.health import HealthStatus

router = APIRouter(tags=["Health"])
logger = logging.getLogger("assetdesk.health")


@router.get(
    "/health",
    response_model=HealthStatus,
    summary="Health check",
    description="No sign-in needed. 200 when the service and its database are reachable, 503 otherwise.",
    responses={503: {"model": HealthStatus, "description": "Running, but the database is unreachable"}},
)
def health(db: DbSession, settings: AppSettings, response: Response) -> HealthStatus:
    try:
        db.execute(select(1))
        db_state = "ok"
    except SQLAlchemyError:
        logger.exception("health check could not reach the database")
        db_state = "unavailable"
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return HealthStatus(
        status="ok" if db_state == "ok" else "degraded",
        version=settings.app_version,
        database=db_state,
    )
