from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from sqlalchemy import text

from app.core.db import get_sessionmaker

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
