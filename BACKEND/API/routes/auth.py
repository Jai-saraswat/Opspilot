"""Authentication routes for the OpsPilot frontend.

All authentication operations delegate to the existing Services layer.
Refresh tokens are stored in HttpOnly cookies; access tokens are returned
in the ServiceResponse JSON envelope.

Business logic, password hashing, session persistence, token creation,
and token revocation remain in Services.
"""

from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, Cookie, Depends
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from BACKEND.API.request_dealer import get_verified_actor_id

from BACKEND.Services.account.login_user import login_user
from BACKEND.Services.account.logout_user import logout_user
from BACKEND.Services.account.refresh_access_token import (
    refresh_access_token,
)
from BACKEND.Services.account.register_user import register_user


router = APIRouter(
    prefix="/auth",
    tags=["Authentication"],
)

REFRESH_COOKIE_NAME = "opspilot_refresh"
REFRESH_COOKIE_MAX_AGE = 30 * 24 * 60 * 60


# ============================================================
# REQUEST MODELS
# ============================================================

class RegisterRequest(BaseModel):
    """Register a new account."""

    model_config = ConfigDict(extra="forbid")

    full_name: str = Field(min_length=1, max_length=150)
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=12, max_length=128)


class LoginRequest(BaseModel):
    """Authenticate with email and password."""

    model_config = ConfigDict(extra="forbid")

    email: str = Field(min_length=1, max_length=254)
    password: str = Field(min_length=1, max_length=128)


# ============================================================
# REFRESH COOKIE CONFIGURATION
# ============================================================

def _cookie_options() -> dict[str, Any]:
    """Return consistent refresh-cookie security settings."""

    same_site = os.getenv(
        "AUTH_COOKIE_SAMESITE",
        "lax",
    ).strip().lower()

    if same_site not in {"lax", "strict", "none"}:
        same_site = "lax"

    secure = (
        os.getenv("AUTH_COOKIE_SECURE", "true")
        .strip()
        .lower()
        in {"1", "true", "yes"}
    )

    # Browsers require Secure for SameSite=None cookies.
    if same_site == "none":
        secure = True

    domain = os.getenv("AUTH_COOKIE_DOMAIN", "").strip() or None

    return {
        "httponly": True,
        "secure": secure,
        "samesite": same_site,
        "path": "/",
        "domain": domain,
    }


# ============================================================
# SERVICE RESPONSE ADAPTER
# ============================================================

def _service_response(
    result: Any,
    *,
    issue_refresh_cookie: bool = False,
    clear_refresh_cookie: bool = False,
) -> JSONResponse:
    """Return a ServiceResponse without exposing refresh tokens."""

    content = jsonable_encoder(result)
    refresh_token = None

    if issue_refresh_cookie and result.success:
        outputs = getattr(result, "outputs", None)
        data = getattr(outputs, "data", None)

        if isinstance(data, dict):
            refresh_token = data.get("refresh_token")

        # Never send the refresh token in the JSON response.
        public_outputs = content.get("outputs", {})
        public_data = public_outputs.get("data")

        if isinstance(public_data, dict):
            public_data.pop("refresh_token", None)

    response = JSONResponse(
        status_code=result.http_status,
        content=content,
        headers={
            "Cache-Control": "no-store",
            "Pragma": "no-cache",
        },
    )

    options = _cookie_options()

    if isinstance(refresh_token, str) and refresh_token:
        response.set_cookie(
            key=REFRESH_COOKIE_NAME,
            value=refresh_token,
            max_age=REFRESH_COOKIE_MAX_AGE,
            **options,
        )

    if clear_refresh_cookie:
        response.delete_cookie(
            key=REFRESH_COOKIE_NAME,
            **options,
        )

    return response


# ============================================================
# REGISTRATION
# ============================================================

@router.post("/register")
def register(
    body: RegisterRequest,
) -> JSONResponse:
    """Create an account and assign the default standard_user role."""

    result = register_user(
        full_name=body.full_name,
        email=body.email,
        password=body.password,
    )

    return _service_response(result)


# ============================================================
# LOGIN
# ============================================================

@router.post("/login")
def login(
    body: LoginRequest,
) -> JSONResponse:
    """Authenticate a user and establish a refresh-token session."""

    result = login_user(
        email=body.email,
        password=body.password,
    )

    return _service_response(
        result,
        issue_refresh_cookie=True,
    )


# ============================================================
# REFRESH ACCESS TOKEN
# ============================================================

@router.post("/refresh")
def refresh(
    refresh_token: str | None = Cookie(
        default=None,
        alias=REFRESH_COOKIE_NAME,
    ),
) -> JSONResponse:
    """Issue a new access token using the refresh cookie."""

    result = refresh_access_token(
        refresh_token=refresh_token or "",
    )

    invalid_refresh = (
        not result.success
        and result.http_status in {401, 403}
    )

    return _service_response(
        result,
        clear_refresh_cookie=invalid_refresh,
    )


# ============================================================
# LOGOUT
# ============================================================

@router.post("/logout")
def logout(
    actor_user_id: str = Depends(get_verified_actor_id),
    refresh_token: str | None = Cookie(
        default=None,
        alias=REFRESH_COOKIE_NAME,
    ),
) -> JSONResponse:
    """Revoke the authenticated user's refresh-token session."""

    result = logout_user(
        user_id=actor_user_id,
        refresh_token=refresh_token or "",
    )

    return _service_response(
        result,
        clear_refresh_cookie=result.success,
    )