from fastapi import APIRouter

from app.schemas.common import HealthOut

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live", response_model=HealthOut)
def live() -> HealthOut:
    return HealthOut(status="ok")
