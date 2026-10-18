"""Retrieve a work item's paginated activity timeline."""

from __future__ import annotations

from uuid import UUID

from BACKEND.Postgres.Operations.activity.errors import ActivityDatabaseError
from BACKEND.Postgres.Operations.activity.list_work_item_activity import (
    list_work_item_activity,
)
from BACKEND.Postgres.Operations.work_items.errors import (
    WorkItemDatabaseError,
)
from BACKEND.Postgres.Operations.work_items.get_work_item_by_id import (
    get_work_item_by_id,
)
from BACKEND.Services.activity._common import (
    active_actor,
    fail,
    parse_identifier,
    public_activities,
    success,
    valid_pagination,
)
from BACKEND.Services.work_management._common import can_view_team


def get_work_item_activity(
    *,
    actor_user_id: UUID | str,
    work_item_id: UUID | str,
    limit: int = 50,
    offset: int = 0,
    action: str | None = None,
):
    name = "get_work_item_activity"
    inputs = {
        "work_item_id": str(work_item_id),
        "limit": limit,
        "offset": offset,
        "action": action,
    }

    actor_id = active_actor(actor_user_id)

    if actor_id is None:
        return fail(
            name=name,
            description="List work-item activity.",
            code="UNAUTHENTICATED",
            message="An active user account is required.",
            status=401,
            inputs=inputs,
        )

    try:
        item_id = parse_identifier(work_item_id)
    except (ValueError, TypeError, AttributeError):
        return fail(
            name=name,
            description="List work-item activity.",
            code="INVALID_WORK_ITEM_ID",
            message="The work-item identifier is invalid.",
            status=400,
            inputs=inputs,
        )

    if not valid_pagination(limit, offset):
        return fail(
            name=name,
            description="List work-item activity.",
            code="INVALID_PAGINATION",
            message="Limit must be 1–100 and offset must be non-negative.",
            status=400,
            inputs=inputs,
        )

    if action is not None and (
        not isinstance(action, str)
        or not action.strip()
        or len(action.strip()) > 50
    ):
        return fail(
            name=name,
            description="List work-item activity.",
            code="INVALID_ACTION",
            message="Action filter must contain 1–50 characters.",
            status=400,
            inputs=inputs,
        )

    try:
        item = get_work_item_by_id(item_id)

        if item is None:
            return fail(
                name=name,
                description="List work-item activity.",
                code="WORK_ITEM_NOT_FOUND",
                message="The work item does not exist.",
                status=404,
                inputs=inputs,
            )

        if not can_view_team(actor_id, item["team_id"]):
            return fail(
                name=name,
                description="List work-item activity.",
                code="FORBIDDEN",
                message="You cannot access this work item's activity.",
                status=403,
                inputs=inputs,
            )

        result = list_work_item_activity(
            item_id,
            limit=limit,
            offset=offset,
            action=action.strip() if action else None,
        )

        return success(
            name=name,
            description="Work-item activity retrieved.",
            data={
                "items": public_activities(result["items"]),
                "total": result["total"],
                "limit": result["limit"],
                "offset": result["offset"],
            },
            inputs=inputs,
        )

    except (ActivityDatabaseError, WorkItemDatabaseError):
        return fail(
            name=name,
            description="List work-item activity.",
            code="DATABASE_ERROR",
            message="The activity timeline could not be retrieved right now.",
            status=500,
            inputs=inputs,
        )
    except ValueError as exc:
        return fail(
            name=name,
            description="List work-item activity.",
            code="INVALID_FILTER",
            message=str(exc),
            status=400,
            inputs=inputs,
        )