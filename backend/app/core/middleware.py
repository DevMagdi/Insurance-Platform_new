"""Correlation id, security headers, client-ip extraction, error envelope rendering."""

from __future__ import annotations

import time
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import HTTPConnection

from app.core.errors import AppError, error_json
from app.core.logging import correlation_id, get_logger

log = get_logger("http")


def client_ip(conn: HTTPConnection, trust_hops: int = 1) -> str | None:
    """X-Forwarded-For is trusted only for the configured number of hops."""
    forwarded = conn.headers.get("x-forwarded-for")
    if forwarded and trust_hops > 0:
        parts = [p.strip() for p in forwarded.split(",") if p.strip()]
        if parts:
            return parts[-min(trust_hops, len(parts))]
    return conn.client.host if conn.client else None


class RequestContext(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        cid = request.headers.get("x-correlation-id") or uuid.uuid4().hex[:12]
        token = correlation_id.set(cid)
        started = time.perf_counter()
        try:
            response = await call_next(request)
        finally:
            correlation_id.reset(token)
        response.headers["x-correlation-id"] = cid
        if request.url.path.startswith("/api"):
            log.info(
                "http",
                method=request.method,
                path=request.url.path,
                status=response.status_code,
                ms=round((time.perf_counter() - started) * 1000, 1),
            )
        return response


class SecurityHeaders(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        response = await call_next(request)
        response.headers.setdefault("x-content-type-options", "nosniff")
        response.headers.setdefault("x-frame-options", "DENY")
        response.headers.setdefault("referrer-policy", "no-referrer")
        response.headers.setdefault("permissions-policy", "geolocation=(), microphone=(), camera=()")
        response.headers.setdefault("cross-origin-opener-policy", "same-origin")
        if request.url.path.startswith("/api") or response.status_code >= 400:
            response.headers.setdefault("cache-control", "no-store")
        return response


def install(app: FastAPI, *, cors_origins: list[str], cookie_secure: bool) -> None:
    from fastapi.middleware.cors import CORSMiddleware

    app.add_middleware(SecurityHeaders)
    app.add_middleware(RequestContext)
    if cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=cors_origins,
            allow_credentials=True,
            allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
            allow_headers=["authorization", "content-type", "x-correlation-id", "idempotency-key"],
        )
    _ = cookie_secure

    @app.exception_handler(AppError)
    async def _app_error(_request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content=exc.detail)

    @app.exception_handler(RequestValidationError)
    async def _validation(_request: Request, exc: RequestValidationError) -> JSONResponse:
        details: list[dict[str, Any]] = [
            {"field": ".".join(str(p) for p in err.get("loc", [])[1:]), "message": err.get("msg"), "type": err.get("type")}
            for err in exc.errors()
        ]
        return JSONResponse(
            status_code=422,
            content=error_json(422, "validation_failed", "Some fields need attention", details),
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:  # pragma: no cover - safety net
        log.error("unhandled", path=request.url.path, error=type(exc).__name__, message=str(exc)[:400])
        return JSONResponse(status_code=500, content=error_json(500, "internal_error", "Unexpected server error"))
