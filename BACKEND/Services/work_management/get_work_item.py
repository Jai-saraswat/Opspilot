"""Retrieve one work item after enforcing team access."""

from __future__ import annotations

from uuid import UUID

from BACKEND.Postgres.Operations.work_items.errors import WorkItemDatabaseError
from BACKEND.Postgres.Operations.work_items.get_work_item_by_id import (
    get_work_item_by_id,
)
from BACKEND.Services.work_management._common import (
    active_actor,
    can_view_team,
    fail,
    parse_identifier,
    public_work_item,
    success,
)


def get_work_item(
    *,
    actor_user_id: UUID | str,
    work_item_id: UUID | str,
):
    name = "get_work_item"
    inputs = {"work_item_id": str(work_item_id)}

    actor_id = active_actor(actor_user_id)

    if actor_id is None:
        return fail(
            name=name,
            description="Retrieve a work item.",
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
            description="Retrieve a work item.",
            code="INVALID_IDENTIFIER",
            message="The work-item identifier is invalid.",
            status=400,
            inputs=inputs,
        )

    try:
        item = get_work_item_by_id(item_id)

        if item is None:
            return fail(
                name=name,
                description="Retrieve a work item.",
                code="WORK_ITEM_NOT_FOUND",
                message="The work item does not exist.",
                status=404,
                inputs=inputs,
            )

        if not can_view_team(actor_id, item["team_id"]):
            return fail(
                name=name,
                description="Retrieve a work item.",
                code="FORBIDDEN",
                message="You do not have access to this work item.",
                status=403,
                inputs=inputs,
            )

        return success(
            name=name,
            description="Work item retrieved.",
            data={"work_item": public_work_item(item)},
            inputs=inputs,
        )

    except WorkItemDatabaseError:
        return fail(
            name=name,
            description="Retrieve a work item.",
            code="DATABASE_ERROR",
            message="The work item could not be retrieved right now.",
            status=500,
            inputs=inputs,
        )