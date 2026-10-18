"""OpsPilot API application entry point.

Responsibilities:
- Receive incoming HTTP requests through FastAPI/Uvicorn.
- Register all domain routers under /api/v1.
- Configure frontend CORS.
- Provide health and database-readiness endpoints.
- Normalize HTTP, validation, and unexpected errors.
- Preserve the established ServiceResponse envelope.

Business authorization and database operations remain in Services
and Operations respectively.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import psycopg
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

# ============================================================
# ENVIRONMENT CONFIGURATION
# ============================================================

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = PROJECT_ROOT / "DEPLOYEMENT" / ".env"

# Load environment configuration before importing application modules.
load_dotenv(ENV_FILE, override=False)

API_PREFIX = "/api/v1"

logger = logging.getLogger("opspilot.api")


# ============================================================
# SHARED RESPONSE HELPERS
# ============================================================

from BACKEND.Services.contracts import service_failure, service_success


def _request_id(request: Request) -> str | None:
    """Read the request ID when another layer has already attached one."""

    value = getattr(request.state, "request_id", None)
    return str(value) if value else None


def _error_response(
    *,
    request: Request,
    status_code: int,
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    """Create a standardized API error without exposing internals."""

    result = service_failure(
        name="api_gateway",
        category="api",
        subcategory="http",
        description="HTTP request processing",
        code=code,
        message=message,
        http_status=status_code,
        details=details or {},
        request_id=_request_id(request),
    )

    response = JSONResponse(
        status_code=status_code,
        content=jsonable_encoder(result),
        headers=headers,
    )
    response.headers["Cache-Control"] = "no-store"
    return response


def _health_response(
    *,
    status: str,
    http_status: int = 200,
) -> JSONResponse:
    """Return a standardized health/readiness response."""

    result = service_success(
        name="api_gateway",
        category="api",
        subcategory="health",
        description="API health and readiness",
        data={"status": status},
        http_status=http_status,
    )

    return JSONResponse(
        status_code=http_status,
        content=jsonable_encoder(result),
        headers={"Cache-Control": "no-store"},
    )


# ============================================================
# APPLICATION
# ============================================================

app = FastAPI(
    title="OpsPilot API",
    description=(
        "Operational work management API. "
        "Business rules and resource authorization are enforced "
        "by the existing Services layer."
    ),
    version="1.0.0",
    openapi_url=f"{API_PREFIX}/openapi.json",
    docs_url=f"{API_PREFIX}/docs",
    redoc_url=f"{API_PREFIX}/redoc",
)


# ============================================================
# FRONTEND CORS
# ============================================================

# Configure FRONTEND_ORIGINS as a comma-separated list of exact origins.
# Example:
# FRONTEND_ORIGINS=http://localhost:3000,https://your-frontend.example
#
# Credentials must not be combined with an unrestricted "*" origin.

_frontend_origins = [
    origin.strip().rstrip("/")
    for origin in os.getenv(
        "FRONTEND_ORIGINS",
        "http://localhost:3000,http://127.0.0.1:3000",
    ).split(",")
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_frontend_origins,
    allow_credentials=True,
    allow_methods=[
        "GET",
        "POST",
        "PATCH",
        "PUT",
        "DELETE",
        "OPTIONS",
    ],
    allow_headers=[
        "Accept",
        "Authorization",
        "Content-Type",
        "Idempotency-Key",
        "X-Request-ID",
    ],
    expose_headers=["X-Request-ID"],
    max_age=600,
)


# ============================================================
# STANDARDIZED ERROR HANDLERS
# ============================================================

@app.exception_handler(RequestValidationError)
async def handle_validation_error(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    """Normalize FastAPI input-validation failures.

    Do not include rejected input values: requests may contain passwords,
    tokens, or other sensitive information.
    """

    errors = [
        {
            "location": list(error.get("loc", ())),
            "message": error.get("msg", "Invalid value."),
            "type": error.get("type", "validation_error"),
        }
        for error in exc.errors()
    ]

    return _error_response(
        request=request,
        status_code=422,
        code="REQUEST_VALIDATION_FAILED",
        message="The request contains invalid or missing fields.",
        details={"errors": errors},
    )


@app.exception_handler(HTTPException)
async def handle_http_error(
    request: Request,
    exc: HTTPException,
) -> JSONResponse:
    """Normalize deliberate HTTP errors from routes and dependencies."""

    status_codes = {
        400: "BAD_REQUEST",
        401: "UNAUTHENTICATED",
        403: "FORBIDDEN",
        404: "NOT_FOUND",
        405: "METHOD_NOT_ALLOWED",
        409: "CONFLICT",
        422: "REQUEST_VALIDATION_FAILED",
        429: "RATE_LIMITED",
    }

    message = (
        exc.detail
        if isinstance(exc.detail, str)
        else "The request could not be completed."
    )

    details = (
        exc.detail
        if isinstance(exc.detail, dict)
        else {}
    )

    return _error_response(
        request=request,
        status_code=exc.status_code,
        code=status_codes.get(
            exc.status_code,
            "HTTP_REQUEST_FAILED",
        ),
        message=message,
        details=details,
        headers=exc.headers,
    )


@app.exception_handler(Exception)
async def handle_unexpected_error(
    request: Request,
    exc: Exception,
) -> JSONResponse:
    """Hide implementation details from unexpected server errors."""

    logger.error(
        "Unhandled API exception: method=%s path=%s",
        request.method,
        request.url.path,
        exc_info=(type(exc), exc, exc.__traceback__),
    )

    return _error_response(
        request=request,
        status_code=500,
        code="INTERNAL_SERVER_ERROR",
        message="An unexpected server error occurred.",
    )


# ============================================================
# DOMAIN ROUTERS
# ============================================================

from BACKEND.API.routes.accounts import router as accounts_router
from BACKEND.API.routes.activity import router as activity_router
from BACKEND.API.routes.approvals import router as approvals_router
from BACKEND.API.routes.auth import router as auth_router
from BACKEND.API.routes.memberships import router as memberships_router
from BACKEND.API.routes.teams import router as teams_router
from BACKEND.API.routes.work_items import router as work_items_router


# All routes share the versioned API prefix.
# Authentication dependencies run before protected route handlers.
for domain_router in (
    auth_router,
    accounts_router,
    teams_router,
    memberships_router,
    work_items_router,
    approvals_router,
    activity_router,
):
    app.include_router(
        domain_router,
        prefix=API_PREFIX,
    )


# ============================================================
# HEALTH AND READINESS
# ============================================================

@app.get(
    "/health",
    tags=["System"],
    include_in_schema=False,
)
def health_check() -> JSONResponse:
    """Liveness endpoint; indicates that the API process is running."""

    return _health_response(status="ok")


@app.get(
    "/ready",
    tags=["System"],
    include_in_schema=False,
)
def readiness_check() -> JSONResponse:
    """Readiness endpoint; verifies database connectivity."""

    from BACKEND.Postgres.gateway import get_connection

    try:
        with get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                cursor.fetchone()

    except Exception:
        logger.exception("API readiness check failed.")

        return _health_response(
            status="not_ready",
            http_status=503,
        )

    return _health_response(status="ready")