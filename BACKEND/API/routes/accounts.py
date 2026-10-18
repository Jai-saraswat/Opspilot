
"""Account and profile API routes.

Responsibilities:
- Validate HTTP request shapes.
- Obtain the trusted actor identity from the shared request dealer.
- Call the existing Services layer.
- Return the ServiceResponse with its intended HTTP status.

Authentication infrastructure, business authorization, database access,
transactions, and idempotency implementation do not belong in this file.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from BACKEND.API.request_dealer import get_verified_actor_id

from BACKEND.Services.account.change_password import change_password
from BACKEND.Services.account.get_account_by_email import (
    get_account_by_email,
)
from BACKEND.Services.account.get_account_by_id import get_account_by_id
from BACKEND.Services.account.get_account_status import get_account_status
from BACKEND.Services.account.get_profile import get_profile
from BACKEND.Services.account.list_accounts import list_accounts
from BACKEND.Services.account.update_account import update_account
from BACKEND.Services.account.update_account_status import (
    update_account_status,
)
from BACKEND.Services.account.update_profile import update_profile


router = APIRouter(
    prefix="/accounts",
    tags=["Accounts"],
)


# ============================================================
# REQUEST MODELS
# ============================================================

class ProfileUpdateRequest(BaseModel):
    """Fields a user can update on their own profile."""

    model_config = ConfigDict(extra="forbid")

    full_name: str | None = None
    email: str | None = None


class PasswordChangeRequest(BaseModel):
    """Change the authenticated user's password."""

    model_config = ConfigDict(extra="forbid")

    current_password: str
    new_password: str


class AccountUpdateRequest(BaseModel):
    """Fields available to authorized account administrators."""

    model_config = ConfigDict(extra="forbid")

    full_name: str | None = None
    email: str | None = None


class AccountStatusUpdateRequest(BaseModel):
    """Change an account's status."""

    model_config = ConfigDict(extra="forbid")

    account_status: str


# ============================================================
# RESPONSE ADAPTER
# ============================================================

def _service_response(result: Any) -> JSONResponse:
    """Preserve the service response envelope and HTTP status."""

    return JSONResponse(
        status_code=result.http_status,
        content=jsonable_encoder(result),
    )


# ============================================================
# CURRENT USER PROFILE
# ============================================================

@router.get("/me")
def read_my_profile(
    actor_user_id: str = Depends(get_verified_actor_id),
) -> JSONResponse:
    """Retrieve the authenticated user's profile."""

    result = get_profile(
        actor_user_id=actor_user_id,
    )

    return _service_response(result)


@router.patch("/me")
def update_my_profile(
    body: ProfileUpdateRequest,
    idempotency_key: str | None = Header(
        default=None,
        alias="Idempotency-Key",
    ),
    actor_user_id: str = Depends(get_verified_actor_id),
) -> JSONResponse:
    """Update the authenticated user's own profile."""

    result = update_profile(
        actor_user_id=actor_user_id,
        full_name=body.full_name,
        email=body.email,
        idempotency_key=idempotency_key,
    )

    return _service_response(result)


@router.patch("/me/password")
def change_my_password(
    body: PasswordChangeRequest,
    idempotency_key: str | None = Header(
        default=None,
        alias="Idempotency-Key",
    ),
    actor_user_id: str = Depends(get_verified_actor_id),
) -> JSONResponse:
    """Change the authenticated user's password."""

    result = change_password(
        user_id=actor_user_id,
        current_password=body.current_password,
        new_password=body.new_password,
        idempotency_key=idempotency_key,
    )

    return _service_response(result)


# ============================================================
# ACCOUNT DIRECTORY
# ============================================================

@router.get("")
def read_accounts(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    account_status: str | None = Query(default=None),
    search: str | None = Query(default=None),
    team_id: str | None = Query(default=None),
    actor_user_id: str = Depends(get_verified_actor_id),
) -> JSONResponse:
    """List accounts or search account candidates for a team.

    Global listing and team-scoped candidate-search permissions are
    enforced by the existing list_accounts Service.
    """

    result = list_accounts(
        actor_user_id=actor_user_id,
        limit=limit,
        offset=offset,
        account_status=account_status,
        search=search,
        team_id=team_id,
    )

    return _service_response(result)


@router.get("/by-email")
def read_account_by_email(
    email: str = Query(..., min_length=1, max_length=254),
    actor_user_id: str = Depends(get_verified_actor_id),
) -> JSONResponse:
    """Retrieve an account by email through the existing Service."""

    result = get_account_by_email(
        actor_user_id=actor_user_id,
        email=email,
    )

    return _service_response(result)


# ============================================================
# INDIVIDUAL ACCOUNT LOOKUPS
# ============================================================

@router.get("/{target_user_id}/status")
def read_account_status(
    target_user_id: UUID,
    actor_user_id: str = Depends(get_verified_actor_id),
) -> JSONResponse:
    """Retrieve an account's status."""

    result = get_account_status(
        actor_user_id=actor_user_id,
        target_user_id=str(target_user_id),
    )

    return _service_response(result)


@router.get("/{target_user_id}")
def read_account(
    target_user_id: UUID,
    actor_user_id: str = Depends(get_verified_actor_id),
) -> JSONResponse:
    """Retrieve an account under the existing authorization policy."""

    result = get_account_by_id(
        actor_user_id=actor_user_id,
        target_user_id=str(target_user_id),
    )

    return _service_response(result)


# ============================================================
# ADMINISTRATIVE ACCOUNT MANAGEMENT
# ============================================================

@router.patch("/{target_user_id}/status")
def change_an_account_status(
    target_user_id: UUID,
    body: AccountStatusUpdateRequest,
    idempotency_key: str | None = Header(
        default=None,
        alias="Idempotency-Key",
    ),
    actor_user_id: str = Depends(get_verified_actor_id),
) -> JSONResponse:
    """Update account status through the existing Service."""

    result = update_account_status(
        actor_user_id=actor_user_id,
        target_user_id=str(target_user_id),
        account_status=body.account_status,
        idempotency_key=idempotency_key,
    )

    return _service_response(result)


@router.patch("/{target_user_id}")
def update_an_account(
    target_user_id: UUID,
    body: AccountUpdateRequest,
    idempotency_key: str | None = Header(
        default=None,
        alias="Idempotency-Key",
    ),
    actor_user_id: str = Depends(get_verified_actor_id),
) -> JSONResponse:
    """Update another account through the existing Service."""

    result = update_account(
        actor_user_id=actor_user_id,
        target_user_id=str(target_user_id),
        full_name=body.full_name,
        email=body.email,
        idempotency_key=idempotency_key,
    )

    return _service_response(result)
