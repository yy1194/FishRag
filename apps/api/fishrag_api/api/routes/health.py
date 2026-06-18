from __future__ import annotations

from fastapi import APIRouter
from fishrag_common.config import get_settings
from starlette.responses import PlainTextResponse

from fishrag_api.observability import metrics_registry

router = APIRouter()


@router.get("/health")
async def health() -> dict[str, str]:
    settings = get_settings()
    return {
        "status": "ok",
        "service": settings.app_name,
        "environment": settings.environment,
    }


@router.get("/metrics", response_class=PlainTextResponse)
async def metrics() -> PlainTextResponse:
    settings = get_settings()
    payload = metrics_registry.render_prometheus(
        service=settings.app_name,
        environment=settings.environment,
    )
    return PlainTextResponse(
        payload,
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )
