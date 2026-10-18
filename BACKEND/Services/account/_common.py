"""Shared helpers for OpsPilot account services."""

from __future__ import annotations

import os
from datetime import datetime, timezone, timedelta
from typing import Any
from uuid import UUID, uuid4

import jwt

from BACKEND.Postgres.Operations.users.get_user_by_id import get_user_by_id
from BACKEND.Services.authorization.context import load_actor_context
from BACKEND.Services.authorization.policy import (
    AuthenticationRequiredError,
    has_permission as policy_has_permission,
)
from BACKEND.Services.contracts import service_failure, service_success


def to_public_user(user: dict[str, Any]) -> dict[str, Any]:
    """Return only approved, non-sensitive user fields."""
    allowed = (
        "id",
        "full_name",
        "email",
        "account_status",
        "created_at",
        "updated_at",
    )

    result: dict[str, Any] = {}

    for key in allowed:
        if key not in user:
            continue

        value = user[key]

        if hasattr(value, "isoformat"):
            value = value.isoformat()
        elif isinstance(value, UUID):
            value = str(value)

        result[key] = value

    return result


def fail(
    *,
    name: str,
    subcategory: str,
    description: str,
    code: str,
    message: str,
    status: int,
    inputs: dict[str, Any] | None = None,
):
    return service_failure(
        name=name,
        category="account",
        subcategory=subcategory,
        description=description,
        code=code,
        message=message,
        http_status=status,
        inputs=inputs or {},
    )


def success(
    *,
    name: str,
    subcategory: str,
    description: str,
    outputs: Any,
    inputs: dict[str, Any] | None = None,
    status: int = 200,
):
    """Build a success response using the existing response contract."""
    return service_success(
        name=name,
        category="account",
        subcategory=subcategory,
        description=description,
        inputs=inputs or {},
        data=outputs,
        http_status=status,
    )


def parse_uuid(value: UUID | str) -> UUID:
    """Convert a user identifier to UUID."""
    return value if isinstance(value, UUID) else UUID(str(value))


def actor_is_active(user_id: UUID | str) -> bool:
    """Check the authoritative account status in PostgreSQL."""
    user = get_user_by_id(parse_uuid(user_id))
    return bool(user and user.get("account_status") == "active")


def actor_has_permission(
    user_id: UUID | str,
    permission_key: str,
    team_id: UUID | str | None = None,
) -> bool:
    """Check a permission using the centralized authorization policy.

    Supplying team_id evaluates applicable team-scoped overrides alongside
    the actor's system-role permissions.
    """
    try:
        parsed_team_id = (
            parse_uuid(team_id) if team_id is not None else None
        )
        actor = load_actor_context(
            user_id,
            team_id=parsed_team_id,
        )
    except AuthenticationRequiredError:
        return False

    return policy_has_permission(
        actor,
        permission_key,
        team_id=parsed_team_id,
    )


def make_access_token(user_id: UUID | str) -> str:
    """Create a short-lived HS256 access token."""
    secret = os.getenv("ACCESS_TOKEN_SECRET", "")

    if len(secret) < 32:
        raise RuntimeError(
            "ACCESS_TOKEN_SECRET must be configured with at least "
            "32 characters of random secret material."
        )

    ttl_seconds = int(
        os.getenv("ACCESS_TOKEN_TTL_SECONDS", "900")
    )

    if not 60 <= ttl_seconds <= 3600:
        raise RuntimeError(
            "ACCESS_TOKEN_TTL_SECONDS must be between 60 and 3600."
        )

    now = datetime.now(timezone.utc)

    payload = {
        "sub": str(user_id),
        "token_type": "access",
        "iat": now,
        "exp": now + timedelta(seconds=ttl_seconds),
        "jti": str(uuid4()),
    }

    return jwt.encode(
        payload,
        secret,
        algorithm="HS256",
    )


def access_token_ttl() -> int:
    return int(
        os.getenv("ACCESS_TOKEN_TTL_SECONDS", "900")
    )