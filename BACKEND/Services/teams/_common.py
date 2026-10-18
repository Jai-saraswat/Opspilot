"""Shared validation, authorization, serialization and response helpers."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from BACKEND.Postgres.Operations.memberships.get_membership import get_membership
from BACKEND.Postgres.Operations.users.get_user_by_id import get_user_by_id
from BACKEND.Services.account._common import (
    actor_has_permission,
    actor_is_active,
    parse_uuid,
)
from BACKEND.Services.contracts import service_failure, service_success


def fail(
    *,
    name: str,
    description: str,
    code: str,
    message: str,
    status: int,
    inputs: dict[str, Any] | None = None,
):
    return service_failure(
        name=name,
        category="teams",
        subcategory="team_management",
        description=description,
        code=code,
        message=message,
        http_status=status,
        inputs=inputs or {},
    )


def success(
    *,
    name: str,
    description: str,
    data: Any,
    inputs: dict[str, Any] | None = None,
    status: int = 200,
):
    return service_success(
        name=name,
        category="teams",
        subcategory="team_management",
        description=description,
        inputs=inputs or {},
        data=data,
        http_status=status,
    )


def public_team(team: dict[str, Any]) -> dict[str, Any]:
    """Expose only approved team fields."""
    allowed = (
        "id",
        "name",
        "description",
        "created_by",
        "created_at",
        "updated_at",
    )
    result: dict[str, Any] = {}

    for key in allowed:
        if key not in team:
            continue

        value = team[key]
        if isinstance(value, UUID):
            value = str(value)
        elif isinstance(value, (datetime, date)):
            value = value.isoformat()

        result[key] = value

    return result


def public_membership(membership: dict[str, Any]) -> dict[str, Any]:
    """Serialize a membership without exposing unrelated user data."""
    result: dict[str, Any] = {}

    for key in ("id", "team_id", "user_id", "role", "joined_at"):
        if key not in membership:
            continue

        value = membership[key]
        if isinstance(value, UUID):
            value = str(value)
        elif isinstance(value, (datetime, date)):
            value = value.isoformat()

        result[key] = value

    return result


def active_actor(actor_user_id: UUID | str) -> UUID | None:
    try:
        actor_id = parse_uuid(actor_user_id)
    except (TypeError, ValueError, AttributeError):
        return None

    return actor_id if actor_is_active(actor_id) else None


def has_permission(
    actor_id: UUID,
    *permission_keys: str,
    team_id: UUID | None = None,
) -> bool:
    """Check permissions, including overrides applicable to this team."""
    return any(
        actor_has_permission(
            actor_id,
            permission,
            team_id=team_id,
        )
        for permission in permission_keys
    )


def membership_for(team_id: UUID, user_id: UUID):
    return get_membership(
        team_id=team_id,
        user_id=user_id,
    )


def can_view_team(actor_id: UUID, team_id: UUID) -> bool:
    """A team member or authorized reader may view team details."""
    if membership_for(team_id, actor_id) is not None:
        return True

    return has_permission(
        actor_id,
        "teams:read:any",
        "teams:list:any",
        "teams:manage:any",
        team_id=team_id,
    )


def can_manage_team(
    actor_id: UUID,
    team_id: UUID,
    *permission_keys: str,
) -> bool:
    """Team leads or actors with applicable permissions may manage a team."""
    membership = membership_for(team_id, actor_id)

    if membership is not None and membership.get("role") == "lead":
        return True

    return has_permission(
        actor_id,
        *permission_keys,
        "teams:manage:any",
        team_id=team_id,
    )


def valid_team_name(name: Any) -> bool:
    return (
        isinstance(name, str)
        and bool(name.strip())
        and len(name.strip()) <= 100
    )


def active_user_exists(user_id: UUID) -> bool:
    user = get_user_by_id(user_id)
    return bool(user and user.get("account_status", "active") == "active")