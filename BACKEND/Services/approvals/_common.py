"""Shared helpers for approval workflow Services."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from BACKEND.Services.contracts import service_failure, service_success
from BACKEND.Services.work_management._common import (
    active_actor,
    can_manage_team,
    can_view_team,
    has_permission,
    is_team_member,
    membership_for,
    parse_identifier,
    record_work_item_activity,
    valid_pagination,
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
        category="approvals",
        subcategory="approval_workflow",
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
        category="approvals",
        subcategory="approval_workflow",
        description=description,
        code=code,
        message=message,
        http_status=status,
        inputs=inputs or {},
    )


def serialize_value(value: Any) -> Any:
    if isinstance(value, UUID):
        return str(value)

    if isinstance(value, (datetime, date)):
        return value.isoformat()

    if isinstance(value, dict):
        return {
            str(key): serialize_value(item)
            for key, item in value.items()
        }

    if isinstance(value, list):
        return [serialize_value(item) for item in value]

    return value


def public_approval(
    approval: dict[str, Any],
) -> dict[str, Any]:
    """Return approval fields and optional joined display fields."""
    allowed = (
        "id",
        "work_item_id",
        "requested_by",
        "approver_id",
        "status",
        "decision_reason",
        "requested_at",
        "decided_at",
        "work_item_title",
        "work_item_priority",
        "requester_name",
        "approver_name",
        "team_id",
    )

    return {
        key: serialize_value(approval[key])
        for key in allowed
        if key in approval
    }


def public_approvals(
    approvals: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [public_approval(item) for item in approvals]


def eligible_approver(team_id: UUID, user_id: UUID) -> bool:
    """Only active team leads and members with the approver role may decide."""
    from BACKEND.Postgres.Operations.users.get_user_by_id import get_user_by_id

    user = get_user_by_id(user_id)
    if user is None or user.get("account_status") != "active":
        return False

    membership = membership_for(team_id, user_id)
    if membership is None:
        return False

    return membership.get("role") in {"lead", "approver"}


def may_assign_approver(actor_id: UUID, team_id: UUID) -> bool:
    return can_manage_team(
        actor_id,
        team_id,
        "approvals:assign:any",
    )


def may_view_approval(
    actor_id: UUID,
    approval: dict[str, Any],
    work_item: dict[str, Any],
) -> bool:
    """A requester may read their request; team readers may read its history."""
    return (
        approval.get("requested_by") == actor_id
        or can_view_team(actor_id, work_item["team_id"])
    )


__all__ = [
    "active_actor",
    "can_manage_team",
    "can_view_team",
    "eligible_approver",
    "fail",
    "has_permission",
    "is_team_member",
    "may_assign_approver",
    "may_view_approval",
    "membership_for",
    "parse_identifier",
    "public_approval",
    "public_approvals",
    "record_work_item_activity",
    "success",
    "valid_pagination",
]