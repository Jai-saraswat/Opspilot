"""Shared validation, membership authorization and response helpers."""

from __future__ import annotations

from uuid import UUID

from BACKEND.Postgres.Operations.memberships.get_membership import (
    get_membership,
)
from BACKEND.Services.teams._common import (
    active_actor,
    fail,
    has_permission,
    public_membership,
    success,
)

VALID_ROLES = frozenset({"lead", "member", "approver"})


def membership_for(team_id: UUID, user_id: UUID):
    return get_membership(
        team_id=team_id,
        user_id=user_id,
    )


def can_view_members(actor_id: UUID, team_id: UUID) -> bool:
    membership = membership_for(team_id, actor_id)

    if membership is not None:
        return True

    return has_permission(
        actor_id,
        "teams:members:read:any",
        "teams:manage:any",
        "teams:list:any",
        team_id=team_id,
    )


def can_manage_members(actor_id: UUID, team_id: UUID) -> bool:
    membership = membership_for(team_id, actor_id)

    if membership is not None and membership.get("role") == "lead":
        return True

    return has_permission(
        actor_id,
        "teams:members:manage:any",
        "teams:manage:any",
        team_id=team_id,
    )


def can_manage_roles(actor_id: UUID, team_id: UUID) -> bool:
    membership = membership_for(team_id, actor_id)

    if membership is not None and membership.get("role") == "lead":
        return True

    return has_permission(
        actor_id,
        "teams:members:role:update:any",
        "teams:manage:any",
        team_id=team_id,
    )


def validate_role(role: str) -> bool:
    return isinstance(role, str) and role in VALID_ROLES


def validate_pagination(limit: int, offset: int) -> str | None:
    if (
        not isinstance(limit, int)
        or isinstance(limit, bool)
        or not 1 <= limit <= 100
    ):
        return "Limit must be between 1 and 100."

    if (
        not isinstance(offset, int)
        or isinstance(offset, bool)
        or offset < 0
    ):
        return "Offset must be zero or greater."

    return None