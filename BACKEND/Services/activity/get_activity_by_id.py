"""Retrieve an activity record after checking work-item access."""

from __future__ import annotations

from uuid import UUID

from BACKEND.Postgres.Operations.activity.errors import ActivityDatabaseError
from BACKEND.Postgres.Operations.activity.get_activity_by_id import (
    get_activity_by_id as get_activity_operation,
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
    public_activity,
    success,
)
from BACKEND.Services.work_management._common import can_view_team


def get_activity_by_id(
    *,
    actor_user_id: UUID | str,
    activity_id: UUID | str,
):
    name = "get_activity_by_id"
    inputs = {"activity_id": str(activity_id)}

    actor_id = active_actor(actor_user_id)

    if actor_id is None:
        return fail(
            name=name,
            description="Retrieve an activity record.",
            code="UNAUTHENTICATED",
            message="An active user account is required.",
            status=401,
            inputs=inputs,
        )

    try:
        resolved_activity_id = parse_identifier(activity_id)
    except (ValueError, TypeError, AttributeError):
        return fail(
            name=name,
            description="Retrieve an activity record.",
            code="INVALID_ACTIVITY_ID",
            message="The activity identifier is invalid.",
            status=400,
            inputs=inputs,
        )

    try:
        activity = get_activity_operation(resolved_activity_id)

        if activity is None:
            return fail(
                name=name,
                description="Retrieve an activity record.",
                code="ACTIVITY_NOT_FOUND",
                message="The activity record does not exist.",
                status=404,
                inputs=inputs,
            )

        item = get_work_item_by_id(activity["work_item_id"])

        if item is None:
            return fail(
                name=name,
                description="Retrieve an activity record.",
                code="WORK_ITEM_NOT_FOUND",
                message="The associated work item does not exist.",
                status=404,
                inputs=inputs,
            )

        if not can_view_team(actor_id, item["team_id"]):
            return fail(
                name=name,
                description="Retrieve an activity record.",
                code="FORBIDDEN",
                message="You cannot access the associated work item's activity.",
                status=403,
                inputs=inputs,
            )

        return success(
            name=name,
            description="Activity record retrieved.",
            data={"activity": public_activity(activity)},
            inputs=inputs,
        )

    except (ActivityDatabaseError, WorkItemDatabaseError):
        return fail(
            name=name,
            description="Retrieve an activity record.",
            code="DATABASE_ERROR",
            message="The activity record could not be retrieved right now.",
            status=500,
            inputs=inputs,
        )