"""List the approval history for a work item."""

from __future__ import annotations

from uuid import UUID

from BACKEND.Postgres.Operations.approvals.errors import ApprovalDatabaseError
from BACKEND.Postgres.Operations.approvals.list_work_item_approvals import (
    list_work_item_approvals,
)
from BACKEND.Postgres.Operations.work_items.errors import WorkItemDatabaseError
from BACKEND.Postgres.Operations.work_items.get_work_item_by_id import (
    get_work_item_by_id,
)
from BACKEND.Services.approvals._common import (
    active_actor,
    can_view_team,
    fail,
    parse_identifier,
    public_approvals,
    success,
    valid_pagination,
)

VALID_STATUSES = {"pending", "approved", "rejected"}


def get_work_item_approvals(
    *,
    actor_user_id: UUID | str,
    work_item_id: UUID | str,
    limit: int = 50,
    offset: int = 0,
    status: str | None = None,
):
    name = "list_work_item_approvals"
    inputs = {
        "work_item_id": str(work_item_id),
        "limit": limit,
        "offset": offset,
        "status": status,
    }

    actor_id = active_actor(actor_user_id)
    if actor_id is None:
        return fail(
            name=name,
            description="List work-item approval history.",
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
            description="List work-item approval history.",
            code="INVALID_WORK_ITEM_ID",
            message="The work-item identifier is invalid.",
            status=400,
            inputs=inputs,
        )

    if not valid_pagination(limit, offset):
        return fail(
            name=name,
            description="List work-item approval history.",
            code="INVALID_PAGINATION",
            message="Limit must be 1–100 and offset must be non-negative.",
            status=400,
            inputs=inputs,
        )

    if status is not None and status not in VALID_STATUSES:
        return fail(
            name=name,
            description="List work-item approval history.",
            code="INVALID_STATUS",
            message="The approval status filter is invalid.",
            status=400,
            inputs=inputs,
        )

    try:
        item = get_work_item_by_id(item_id)

        if item is None:
            return fail(
                name=name,
                description="List work-item approval history.",
                code="WORK_ITEM_NOT_FOUND",
                message="The work item does not exist.",
                status=404,
                inputs=inputs,
            )

        if not can_view_team(actor_id, item["team_id"]):
            return fail(
                name=name,
                description="List work-item approval history.",
                code="FORBIDDEN",
                message="You cannot access approval history for this team.",
                status=403,
                inputs=inputs,
            )

        result = list_work_item_approvals(
            item_id,
            limit=limit,
            offset=offset,
            status=status,
        )

        return success(
            name=name,
            description="Work-item approval history retrieved.",
            data={
                "items": public_approvals(result["items"]),
                "total": result["total"],
                "limit": result["limit"],
                "offset": result["offset"],
            },
            inputs=inputs,
        )

    except WorkItemDatabaseError:
        return fail(
            name=name,
            description="List work-item approval history.",
            code="DATABASE_ERROR",
            message="The work item could not be retrieved right now.",
            status=500,
            inputs=inputs,
        )
    except ApprovalDatabaseError:
        return fail(
            name=name,
            description="List work-item approval history.",
            code="DATABASE_ERROR",
            message="Approval history could not be retrieved right now.",
            status=500,
            inputs=inputs,
        )
    except ValueError as exc:
        return fail(
            name=name,
            description="List work-item approval history.",
            code="INVALID_FILTER",
            message=str(exc),
            status=400,
            inputs=inputs,
        )