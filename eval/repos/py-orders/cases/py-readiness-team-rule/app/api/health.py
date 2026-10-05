from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import Engine, text
from sqlalchemy.exc import SQLAlchemyError

from app.core.db import get_engine
from app.core.logging import get_logger
from app.schemas.common import HealthOut

log = get_logger(__name__)

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live", response_model=HealthOut)
def live() -> HealthOut:
    return HealthOut(status="ok")


@router.get("/ready", response_model=HealthOut)
def ready(response: Response, engine: Engine = Depends(get_engine)) -> HealthOut:
    # check the db

    try:
        with engine.connect() as c:
            c.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        log.warning("readiness_check_failed", error=str(exc))
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return HealthOut(status="unavailable")
    return HealthOut(status="ok")
