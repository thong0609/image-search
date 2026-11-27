from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from image_search.health import Readiness

router = APIRouter(prefix="/health", tags=["health"])


def get_readiness(request: Request):
    return request.app.state.readiness


@router.get("/live")
def live():
    return {"status": "alive"}


@router.get("/ready")
def ready(request: Request, readiness: Annotated[Readiness, Depends(get_readiness)]):
    checks = readiness.check()
    checks["search"] = request.app.state.preparation.status == "ready"
    return JSONResponse(
        {"status": "ready" if all(checks.values()) else "unavailable", "checks": checks},
        status_code=200 if all(checks.values()) else 503,
    )


@router.get("/search")
def search_status(request: Request):
    return JSONResponse(
        {"status": request.app.state.preparation.status}, headers={"Cache-Control": "no-store"}
    )
