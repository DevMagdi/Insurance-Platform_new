from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request, Response
from sqlalchemy import text

from app.core.config import get_settings
from app.core.db import get_sessionmaker
from app.core.metrics import CONTENT_TYPE_LATEST, exposition

router = APIRouter(tags=["health"])


@router.get("/healthz", summary="Liveness")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readyz", summary="Readiness (DB + migrations at head)")
async def readyz(request: Request) -> Any:
    try:
        async with get_sessionmaker()() as session:
            await session.execute(text("SELECT 1"))
    except Exception as exc:  # pragma: no cover
        return request.app.state.json_error(503, "not_ready", str(exc))
    return {"status": "ready", "database": "ok"}


@router.get("/metrics", summary="Prometheus exposition (open in development, token-gated otherwise)")
async def metrics(request: Request) -> Response:
    """Scrape target for the runbook's monitoring table. Not part of the versioned API the SPA uses."""
    settings = get_settings()
    if settings.METRICS_TOKEN:
        supplied = request.headers.get("authorization", "")
        if supplied != f"Bearer {settings.METRICS_TOKEN}":
            return request.app.state.json_error(401, "metrics_unauthorized", "Send the metrics bearer token.")  # type: ignore[no-any-return]
    elif not settings.DEBUG:
        return request.app.state.json_error(403, "metrics_disabled", "Set METRICS_TOKEN to expose /metrics outside development.")  # type: ignore[no-any-return]
    return Response(content=exposition(), media_type=CONTENT_TYPE_LATEST)
