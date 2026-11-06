from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from image_search.api.dependencies import get_readiness
from image_search.health import Readiness

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live")
def live():
    return {"status": "alive"}


@router.get("/ready")
def ready(readiness: Annotated[Readiness, Depends(get_readiness)]):
    checks = readiness.check()
    return JSONResponse(
        {"status": "ready" if all(checks.values()) else "unavailable", "checks": checks},
        status_code=200 if all(checks.values()) else 503,
    )
