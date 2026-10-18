"""List work items with database filtering, pagination, and access checks."""

from __future__ import annotations

from uuid import UUID

from BACKEND.Postgres.Operations.work_items.errors import WorkItemDatabaseError
from BACKEND.Postgres.Operations.work_items.list_work_items import (
    list_work_items as list_work_items_operation,
)
from BACKEND.Services.work_management._common import (
    active_actor,
    can_view_team,
    fail,
    has_permission,
    parse_identifier,
    public_work_items,
    success,
    valid_pagination,
)

VALID_STATUSES = {
    "open",
    "in_progress",
    "pending_approval",
    "resolved",
    "cancelled",
}
VALID_PRIORITIES = {"low", "medium", "high", "critical"}
VALID_TYPES = {"investigation", "action", "incident", "approval"}


def list_work_items(
    *,
    actor_user_id: UUID | str,
    team_id: UUID | str | None = None,
    limit: int = 50,
    offset: int = 0,
    assignee_id: UUID | str | None = None,
    unassigned_only: bool = False,
    status: str | None = None,
    priority: str | None = None,
    type: str | None = None,
    search: str | None = None,
):
    name = "list_work_items"
    inputs = {
        "team_id": str(team_id) if team_id is not None else None,
        "limit": limit,
        "offset": offset,
        "status": status,
        "priority": priority,
        "type": type,
        "unassigned_only": unassigned_only,
    }

    actor_id = active_actor(actor_user_id)
    if actor_id is None:
        return fail(
            name=name,
            description="List work items.",
            code="UNAUTHENTICATED",
            message="An active user account is required.",
            status=401,
            inputs=inputs,
        )

    if not valid_pagination(limit, offset):
        return fail(
            name=name,
            description="List work items.",
            code="INVALID_PAGINATION",
            message="Limit must be 1–100 and offset must be non-negative.",
            status=400,
            inputs=inputs,
        )

    if status is not None and status not in VALID_STATUSES:
        return fail(
            name=name,
            description="List work items.",
            code="INVALID_STATUS",
            message="The status filter is invalid.",
            status=400,
            inputs=inputs,
        )

    if priority is not None and priority not in VALID_PRIORITIES:
        return fail(
            name=name,
            description="List work items.",
            code="INVALID_PRIORITY",
            message="The priority filter is invalid.",
            status=400,
            inputs=inputs,
        )

    if type is not None and type not in VALID_TYPES:
        return fail(
            name=name,
            description="List work items.",
            code="INVALID_TYPE",
            message="The type filter is invalid.",
            status=400,
            inputs=inputs,
        )

    if not isinstance(unassigned_only, bool):
        return fail(
            name=name,
            description="List work items.",
            code="INVALID_FILTER",
            message="unassigned_only must be a boolean.",
            status=400,
            inputs=inputs,
        )

    if unassigned_only and assignee_id is not None:
        return fail(
            name=name,
            description="List work items.",
            code="CONFLICTING_FILTERS",
            message="Specify assignee_id or unassigned_only, not both.",
            status=400,
            inputs=inputs,
        )

    try:
        resolved_team_id: UUID | None = None
        resolved_assignee_id: UUID | None = None

        if team_id is not None:
            resolved_team_id = parse_identifier(team_id)

            if not can_view_team(actor_id, resolved_team_id):
                return fail(
                    name=name,
                    description="List work items.",
                    code="FORBIDDEN",
                    message="You cannot view work items for this team.",
                    status=403,
                    inputs=inputs,
                )
        elif not has_permission(
            actor_id,
            "work_items:list:any",
            "work_items:read:any",
            "work_items:manage:any",
        ):
            return fail(
                name=name,
                description="List work items.",
                code="TEAM_FILTER_REQUIRED",
                message="Specify a team you can access. An unscoped list requires global read permission.",
                status=403,
                inputs=inputs,
            )

        if assignee_id is not None:
            resolved_assignee_id = parse_identifier(assignee_id)

        result = list_work_items_operation(
            limit=limit,
            offset=offset,
            team_id=resolved_team_id,
            assignee_id=resolved_assignee_id,
            unassigned_only=unassigned_only,
            status=status,
            priority=priority,
            type=type,
            search=search,
        )

        return success(
            name=name,
            description="Work items listed.",
            data={
                "items": public_work_items(result["items"]),
                "total": result["total"],
                "limit": result["limit"],
                "offset": result["offset"],
            },
            inputs=inputs,
        )

    except (ValueError, TypeError, AttributeError):
        return fail(
            name=name,
            description="List work items.",
            code="INVALID_IDENTIFIER",
            message="A team or assignee identifier is invalid.",
            status=400,
            inputs=inputs,
        )
    except WorkItemDatabaseError:
        return fail(
            name=name,
            description="List work items.",
            code="DATABASE_ERROR",
            message="Work items could not be retrieved right now.",
            status=500,
            inputs=inputs,
        )