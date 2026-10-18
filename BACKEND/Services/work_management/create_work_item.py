"""Create a work item and its creation activity atomically."""

from __future__ import annotations

from uuid import UUID

from BACKEND.Postgres.Operations.activity.errors import (
    ActivityDatabaseError,
    ActivityRelatedRecordNotFoundError,
    InvalidActivityRecordError,
)
from BACKEND.Postgres.Operations.work_items.create_work_item import (
    create_work_item as create_work_item_operation,
)
from BACKEND.Postgres.Operations.work_items.errors import (
    InvalidWorkItemRecordError,
    WorkItemDatabaseError,
    WorkItemRelatedRecordNotFoundError,
)
from BACKEND.Services.idempotency import execute_idempotently
from BACKEND.Services.work_management._common import (
    active_actor,
    active_user_in_team,
    can_create_in_team,
    fail,
    get_team_or_none,
    parse_identifier,
    public_work_item,
    record_work_item_activity,
    success,
)

VALID_TYPES = {"investigation", "action", "incident", "approval"}
VALID_PRIORITIES = {"low", "medium", "high", "critical"}


def create_work_item(
    *,
    actor_user_id: UUID | str,
    title: str,
    description: str,
    type: str,
    team_id: UUID | str,
    priority: str = "medium",
    assignee_id: UUID | str | None = None,
    idempotency_key: str | None = None,
):
    name = "create_work_item"
    inputs = {
        "team_id": str(team_id),
        "type": type,
        "priority": priority,
        "has_assignee": assignee_id is not None,
    }

    actor_id = active_actor(actor_user_id)
    if actor_id is None:
        return fail(
            name=name,
            description="Create a work item.",
            code="UNAUTHENTICATED",
            message="An active user account is required.",
            status=401,
            inputs=inputs,
        )

    try:
        resolved_team_id = parse_identifier(team_id)
        resolved_assignee_id = (
            parse_identifier(assignee_id)
            if assignee_id is not None
            else None
        )
    except ValueError:
        return fail(
            name=name,
            description="Create a work item.",
            code="INVALID_IDENTIFIER",
            message="The team or assignee identifier is invalid.",
            status=400,
            inputs=inputs,
        )

    if (
        not isinstance(title, str)
        or not title.strip()
        or len(title.strip()) > 200
    ):
        return fail(
            name=name,
            description="Create a work item.",
            code="INVALID_TITLE",
            message="Title must contain 1–200 characters.",
            status=400,
            inputs=inputs,
        )

    if not isinstance(description, str) or not description.strip():
        return fail(
            name=name,
            description="Create a work item.",
            code="INVALID_DESCRIPTION",
            message="Description must not be empty.",
            status=400,
            inputs=inputs,
        )

    if type not in VALID_TYPES:
        return fail(
            name=name,
            description="Create a work item.",
            code="INVALID_TYPE",
            message=f"Type must be one of: {', '.join(sorted(VALID_TYPES))}.",
            status=400,
            inputs=inputs,
        )

    if priority not in VALID_PRIORITIES:
        return fail(
            name=name,
            description="Create a work item.",
            code="INVALID_PRIORITY",
            message=f"Priority must be one of: {', '.join(sorted(VALID_PRIORITIES))}.",
            status=400,
            inputs=inputs,
        )

    normalized_title = title.strip()
    normalized_description = description.strip()

    try:
        def _create(connection):
            team = get_team_or_none(resolved_team_id)

            if team is None:
                return fail(
                    name=name,
                    description="Create a work item.",
                    code="TEAM_NOT_FOUND",
                    message="The specified team does not exist.",
                    status=404,
                    inputs=inputs,
                )

            if not can_create_in_team(actor_id, resolved_team_id):
                return fail(
                    name=name,
                    description="Create a work item.",
                    code="FORBIDDEN",
                    message="You cannot create work items for this team.",
                    status=403,
                    inputs=inputs,
                )

            if (
                resolved_assignee_id is not None
                and not active_user_in_team(
                    resolved_assignee_id,
                    resolved_team_id,
                )
            ):
                return fail(
                    name=name,
                    description="Create a work item.",
                    code="INVALID_ASSIGNEE",
                    message=(
                        "The assignee must be an active member "
                        "of the selected team."
                    ),
                    status=400,
                    inputs=inputs,
                )

            created = create_work_item_operation(
                title=normalized_title,
                description=normalized_description,
                type=type,
                team_id=resolved_team_id,
                created_by=actor_id,
                priority=priority,
                assignee_id=resolved_assignee_id,
                connection=connection,
            )

            record_work_item_activity(
                connection=connection,
                work_item_id=created["id"],
                actor_id=actor_id,
                action="work_item_created",
                details={
                    "title": created["title"],
                    "type": created["type"],
                    "status": created["status"],
                    "priority": created["priority"],
                    "assignee_id": (
                        str(created["assignee_id"])
                        if created.get("assignee_id")
                        else None
                    ),
                },
            )

            return success(
                name=name,
                description="Work item created.",
                data={"work_item": public_work_item(created)},
                status=201,
                inputs=inputs,
            )

        return execute_idempotently(
            user_id=actor_id,
            idempotency_key=idempotency_key,
            operation_name=name,
            category="work_management",
            subcategory="work_items",
            description="Create a work item.",
            payload={
                "title": normalized_title,
                "description": normalized_description,
                "type": type,
                "team_id": str(resolved_team_id),
                "priority": priority,
                "assignee_id": (
                    str(resolved_assignee_id)
                    if resolved_assignee_id is not None
                    else None
                ),
            },
            operation=_create,
        )

    except InvalidWorkItemRecordError:
        return fail(
            name=name,
            description="Create a work item.",
            code="INVALID_WORK_ITEM",
            message="One or more work-item fields are invalid.",
            status=400,
            inputs=inputs,
        )
    except (
        WorkItemRelatedRecordNotFoundError,
        ActivityRelatedRecordNotFoundError,
    ):
        return fail(
            name=name,
            description="Create a work item.",
            code="RELATED_RECORD_NOT_FOUND",
            message=(
                "The team, creator, assignee, or activity reference "
                "could not be found."
            ),
            status=404,
            inputs=inputs,
        )
    except InvalidActivityRecordError:
        return fail(
            name=name,
            description="Create a work item.",
            code="ACTIVITY_WRITE_FAILED",
            message=(
                "The creation event could not be recorded; "
                "the work item was not committed."
            ),
            status=500,
            inputs=inputs,
        )
    except (WorkItemDatabaseError, ActivityDatabaseError):
        return fail(
            name=name,
            description="Create a work item.",
            code="DATABASE_ERROR",
            message="The work item could not be created right now.",
            status=500,
            inputs=inputs,
        )