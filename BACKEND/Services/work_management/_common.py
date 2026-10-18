"""Shared helpers for work-management Services."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from BACKEND.Postgres.Operations.activity.create_activity import (
    create_activity as create_activity_operation,
)
from BACKEND.Postgres.Operations.memberships.get_membership import (
    get_membership,
)
from BACKEND.Postgres.Operations.teams.get_team_by_id import get_team_by_id
from BACKEND.Postgres.Operations.users.get_user_by_id import get_user_by_id
from BACKEND.Services.account._common import (
    actor_has_permission,
    actor_is_active,
    parse_uuid,
)
from BACKEND.Services.contracts import service_failure, service_success


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
        category="work_management",
        subcategory="work_items",
        description=description,
        inputs=inputs or {},
        data=data,
        http_status=status,
    )


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
        category="work_management",
        subcategory="work_items",
        description=description,
        code=code,
        message=message,
        http_status=status,
        inputs=inputs or {},
    )


def parse_identifier(value: UUID | str) -> UUID:
    """Parse an identifier into UUID or raise ValueError."""
    try:
        return parse_uuid(value)
    except (TypeError, ValueError, AttributeError) as exc:
        raise ValueError("A valid UUID is required.") from exc


def active_actor(actor_user_id: UUID | str) -> UUID | None:
    """Return the actor UUID only when the account is active."""
    try:
        actor_id = parse_identifier(actor_user_id)
    except (TypeError, ValueError, AttributeError):
        return None

    return actor_id if actor_is_active(actor_id) else None


def has_permission(
    actor_id: UUID,
    *permission_keys: str,
    team_id: UUID | None = None,
) -> bool:
    """Check one or more permissions in the optional team context."""
    return any(
        actor_has_permission(
            actor_id,
            key,
            team_id=team_id,
        )
        for key in permission_keys
    )


def membership_for(
    team_id: UUID,
    actor_id: UUID,
) -> dict[str, Any] | None:
    return get_membership(
        team_id=team_id,
        user_id=actor_id,
    )


def is_team_member(team_id: UUID, user_id: UUID) -> bool:
    return membership_for(team_id, user_id) is not None


def can_view_team(actor_id: UUID, team_id: UUID) -> bool:
    """A team member or authorized reader may view team work."""
    if is_team_member(team_id, actor_id):
        return True

    return has_permission(
        actor_id,
        "work_items:read:any",
        "work_items:list:any",
        "work_items:manage:any",
        team_id=team_id,
    )


def can_create_in_team(actor_id: UUID, team_id: UUID) -> bool:
    if is_team_member(team_id, actor_id):
        return True

    return has_permission(
        actor_id,
        "work_items:create:any",
        "work_items:manage:any",
        team_id=team_id,
    )


def can_manage_team(
    actor_id: UUID,
    team_id: UUID,
    *permission_keys: str,
) -> bool:
    """Team leads or authorized actors may manage work in the team."""
    membership = membership_for(team_id, actor_id)

    if membership is not None and membership.get("role") == "lead":
        return True

    return has_permission(
        actor_id,
        *permission_keys,
        "work_items:manage:any",
        team_id=team_id,
    )


def can_edit_item(actor_id: UUID, item: dict[str, Any]) -> bool:
    """Allow team leads/managers or members who created/own the item."""
    team_id = item["team_id"]

    if can_manage_team(
        actor_id,
        team_id,
        "work_items:update:any",
    ):
        return True

    if not is_team_member(team_id, actor_id):
        return False

    return actor_id in {
        item.get("created_by"),
        item.get("assignee_id"),
    }


def active_user_in_team(user_id: UUID, team_id: UUID) -> bool:
    user = get_user_by_id(user_id)

    if user is None or user.get("account_status") != "active":
        return False

    return is_team_member(team_id, user_id)


def get_team_or_none(team_id: UUID) -> dict[str, Any] | None:
    return get_team_by_id(team_id)


def serialize_value(value: Any) -> Any:
    """Convert database values to JSON-friendly values."""
    if isinstance(value, UUID):
        return str(value)

    if isinstance(value, (datetime, date)):
        return value.isoformat()

    if isinstance(value, dict):
        return {
            str(key): serialize_value(item)
            for key, item in value.items()
        }

    if isinstance(value, (list, tuple)):
        return [serialize_value(item) for item in value]

    return value


def public_work_item(item: dict[str, Any]) -> dict[str, Any]:
    allowed = (
        "id",
        "title",
        "description",
        "type",
        "status",
        "priority",
        "team_id",
        "created_by",
        "assignee_id",
        "created_at",
        "updated_at",
        "completed_at",
    )

    return {
        key: serialize_value(item[key])
        for key in allowed
        if key in item
    }


def public_work_items(
    items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [public_work_item(item) for item in items]


def valid_pagination(limit: int, offset: int) -> bool:
    return (
        isinstance(limit, int)
        and not isinstance(limit, bool)
        and 1 <= limit <= 100
        and isinstance(offset, int)
        and not isinstance(offset, bool)
        and offset >= 0
    )


def record_work_item_activity(
    *,
    connection,
    work_item_id: UUID,
    actor_id: UUID,
    action: str,
    details: dict[str, Any],
) -> dict[str, Any]:
    """Insert activity into the caller's transaction.

    Errors intentionally propagate so the business mutation rolls back if
    the activity event cannot be saved.
    """
    return create_activity_operation(
        work_item_id=work_item_id,
        actor_id=actor_id,
        action=action,
        details=details,
        connection=connection,
    )