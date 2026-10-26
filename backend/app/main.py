"""Broker Hub API application factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute

from app.api.v1.endpoints.health import router as health_router
from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.errors import error_json
from app.core.logging import get_logger, setup_logging
from app.core.middleware import client_ip, install

log = get_logger("app")

DESCRIPTION = """
Broker Hub — insurance brokerage platform (Phase 1: service desk + leads + client files + portal).

* All list and detail endpoints are **data-scoped on the server**: a sales rep only ever sees their
  own leads (`assigned_to`) and clients (`account_owner_id`); an id outside the caller's scope is
  answered with **404**, never 403.
* Arabic-first API messages are the client's job; codes are stable machine keys.
* Every non-2xx body is the uniform `ErrorResponse` envelope `{code, message, details}`.
* Phase 2 groups (`/policies`, `/commissions`, `/issuing-cases`, `/reports/*`) answer
  `503 feature_disabled` until the `phase2.enabled` flag is on.
"""


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    setup_logging(json_logs=not settings.DEBUG)
    log.info("startup", env=settings.ENV, driver=settings.INTEGRATIONS_DRIVER, postgres=settings.is_postgres)
    # The settings rows are the source of truth for provider credentials (ADR-016); the process loads them
    # once here and again on every save. Logged after priming so the line says what the screen says.
    if not settings.is_postgres and settings.DEBUG:
        from app.core.db import create_dev_schema

        await create_dev_schema()
        log.info("dev_schema_created", note="SQLite dev mode — run alembic in prod")
    from app.core.db import get_sessionmaker
    from app.integrations import registry

    async with get_sessionmaker()() as session:
        await registry.prime(session)
    log.info("integrations_primed", live=[p for p in ("whatsapp", "telephony", "email") if registry.live_mode(p)])
    yield
    log.info("shutdown")


def _decorate_openapi(app: FastAPI) -> None:
    """Publish the uniform error envelope in the contract on every non-2xx response.

    The exception handlers build `ErrorResponse` bodies by hand, so OpenAPI would otherwise show a
    bare `application/json` for them — and the generated frontend types would have no error model.
    """
    from app.schemas.auth import ErrorResponse

    def build() -> dict[str, Any]:
        cached = app.openapi_schema
        if cached:
            return cached
        schema = get_openapi(title=app.title, version=app.version, description=app.description, routes=app.routes)
        schemas = schema.setdefault("components", {}).setdefault("schemas", {})
        schemas["ErrorResponse"] = ErrorResponse.model_json_schema()
        for path_item in schema.get("paths", {}).values():
            for operation in path_item.values():
                if not isinstance(operation, dict):
                    continue
                for status_code, response in operation.get("responses", {}).items():
                    if status_code.startswith(("1", "2")):
                        continue
                    response["content"] = {"application/json": {"schema": {"$ref": "#/components/schemas/ErrorResponse"}}}
        app.openapi_schema = schema
        return schema

    app.openapi = build  # type: ignore[method-assign]


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Broker Hub API",
        version="0.6.0",
        description=DESCRIPTION,
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        generate_unique_id_function=_operation_id,
    )
    install(app, cors_origins=settings.CORS_ORIGINS, cookie_secure=settings.COOKIE_SECURE)
    app.state.json_error = _json_error

    @app.middleware("http")
    async def _metrics(request: Any, call_next: Any) -> Any:
        """One place that counts every request, labelled by the matched route template."""
        import time

        from app.core import metrics

        started = time.perf_counter()
        metrics.IN_FLIGHT.inc()
        status = 500
        try:
            response = await call_next(request)
            status = int(response.status_code)
            return response
        finally:
            metrics.IN_FLIGHT.dec()
            route = getattr(request.scope.get("route"), "path", None) or "unmatched"
            metrics.observe(request.method, str(route), status, time.perf_counter() - started)

    @app.middleware("http")
    async def _bind_ip(request: Any, call_next: Any) -> Any:
        from app.middleware_ip import set_client_ip

        set_client_ip(client_ip(request, settings.TRUST_HOPS))
        return await call_next(request)

    app.include_router(api_router, prefix=settings.API_V1_PREFIX)
    # Ops probes stay at the root so container healthchecks do not need to know the API prefix.
    app.include_router(health_router)

    @app.get("/", include_in_schema=False)
    async def root() -> dict[str, str]:
        return {"name": settings.APP_NAME, "docs": "/docs", "api": settings.API_V1_PREFIX}

    @app.exception_handler(404)
    async def _not_found(_request: Any, exc: Any) -> JSONResponse:
        # The app's own `NotFound` *is* an HTTPException with status 404, so a handler keyed on the status
        # sees both kinds. Answering "Route not found" to a request that hit its route and missed a row throws
        # away the reason the service gave ("Lead not found", "Import job not found") — which is exactly what
        # a client has to show a manager. Only a genuinely unmatched route gets the generic answer.
        detail = getattr(exc, "detail", None)
        if isinstance(detail, dict) and detail.get("code"):
            return JSONResponse(status_code=404, content={**detail, "status_code": 404})
        return JSONResponse(status_code=404, content=error_json(404, "not_found", "Route not found"))

    _decorate_openapi(app)
    return app


def _json_error(status_code: int, code: str, message: str, details: Any = None) -> JSONResponse:
    return JSONResponse(status_code=status_code, content=error_json(status_code, code, message, details))


def _operation_id(route: APIRoute) -> str:
    """Stable, collision-free operation ids — openapi-typescript turns them into client methods."""
    method = sorted(route.methods or {"get"})[0].lower()
    path = route.path_format or route.path
    parts = [part for part in path.split("/") if part]
    cleaned = [part.strip("{}").replace("_", " ").title().replace(" ", "") for part in parts]
    return method + "".join(cleaned)


#: Module-level instance so `uvicorn app.main:app` works (compose, the Dockerfile CMD, the e2e
#: webServer and every container healthcheck all reference it; the factory stays for tests).
app = create_app()
