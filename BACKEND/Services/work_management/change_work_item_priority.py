"""Change work-item priority and record the change atomically."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from BACKEND.Postgres.Operations.activity.errors import (
    ActivityDatabaseError,
    ActivityRelatedRecordNotFoundError,
    InvalidActivityRecordError,
)
from BACKEND.Postgres.Operations.work_items.errors import (
    InvalidWorkItemRecordError,
    WorkItemDatabaseError,
)
from BACKEND.Postgres.Operations.work_items.get_work_item_by_id import (
    get_work_item_by_id,
)
from BACKEND.Postgres.Operations.work_items.update_work_item_priority import (
    update_work_item_priority,
)
from BACKEND.Services.idempotency import execute_idempotently
from BACKEND.Services.work_management._common import (
    active_actor,
    can_manage_team,
    can_view_team,
    fail,
    parse_identifier,
    public_work_item,
    record_work_item_activity,
    success,
)
from BACKEND.Services.work_management.update_work_item import (
    _parse_expected_timestamp,
)

VALID_PRIORITIES = {"low", "medium", "high", "critical"}


def change_work_item_priority(
    *,
    actor_user_id: UUID | str,
    work_item_id: UUID | str,
    priority: str,
    expected_updated_at: datetime | str,
    idempotency_key: str | None = None,
):
    name = "change_work_item_priority"
    inputs = {
        "work_item_id": str(work_item_id),
        "priority": priority,
    }

    actor_id = active_actor(actor_user_id)
    if actor_id is None:
        return fail(
            name=name,
            description="Change work-item priority.",
            code="UNAUTHENTICATED",
            message="An active user account is required.",
            status=401,
            inputs=inputs,
        )

    try:
        item_id = parse_identifier(work_item_id)
        expected = _parse_expected_timestamp(expected_updated_at)
    except (ValueError, TypeError, AttributeError):
        return fail(
            name=name,
            description="Change work-item priority.",
            code="INVALID_INPUT",
            message="Provide a valid UUID and timezone-aware timestamp.",
            status=400,
            inputs=inputs,
        )

    if priority not in VALID_PRIORITIES:
        return fail(
            name=name,
            description="Change work-item priority.",
            code="INVALID_PRIORITY",
            message=f"Priority must be one of: {', '.join(sorted(VALID_PRIORITIES))}.",
            status=400,
            inputs=inputs,
        )

    try:
        def _change_priority(connection):
            current = get_work_item_by_id(
                item_id,
                connection=connection,
            )

            if current is None:
                return fail(
                    name=name,
                    description="Change work-item priority.",
                    code="WORK_ITEM_NOT_FOUND",
                    message="The work item does not exist.",
                    status=404,
                    inputs=inputs,
                )

            team_id = current["team_id"]

            if not can_view_team(actor_id, team_id):
                return fail(
                    name=name,
                    description="Change work-item priority.",
                    code="FORBIDDEN",
                    message="You cannot access this work item.",
                    status=403,
                    inputs=inputs,
                )

            if not can_manage_team(
                actor_id,
                team_id,
                "work_items:priority:any",
            ):
                return fail(
                    name=name,
                    description="Change work-item priority.",
                    code="FORBIDDEN",
                    message=(
                        "You are not authorized to change this item's priority."
                    ),
                    status=403,
                    inputs=inputs,
                )

            if current["priority"] == priority:
                if current["updated_at"] != expected:
                    return fail(
                        name=name,
                        description="Change work-item priority.",
                        code="STALE_WORK_ITEM",
                        message=(
                            "The work item changed since you last read it."
                        ),
                        status=409,
                        inputs=inputs,
                    )

                return success(
                    name=name,
                    description=(
                        "The work item already has the requested priority."
                    ),
                    data={"work_item": public_work_item(current)},
                    inputs=inputs,
                )

            updated = update_work_item_priority(
                item_id,
                priority,
                expected_updated_at=expected,
                connection=connection,
            )

            if updated is None:
                latest = get_work_item_by_id(
                    item_id,
                    connection=connection,
                )

                if latest is None:
                    return fail(
                        name=name,
                        description="Change work-item priority.",
                        code="WORK_ITEM_NOT_FOUND",
                        message="The work item no longer exists.",
                        status=404,
                        inputs=inputs,
                    )

                return fail(
                    name=name,
                    description="Change work-item priority.",
                    code="STALE_WORK_ITEM",
                    message=(
                        "The work item changed. Retrieve the latest "
                        "version and retry."
                    ),
                    status=409,
                    inputs=inputs,
                )

            record_work_item_activity(
                connection=connection,
                work_item_id=item_id,
                actor_id=actor_id,
                action="priority_changed",
                details={
                    "old_priority": current["priority"],
                    "new_priority": updated["priority"],
                },
            )

            return success(
                name=name,
                description="Work-item priority updated.",
                data={"work_item": public_work_item(updated)},
                inputs=inputs,
            )

        return execute_idempotently(
            user_id=actor_id,
            idempotency_key=idempotency_key,
            operation_name=name,
            category="work_management",
            subcategory="work_items",
            description="Change work-item priority.",
            payload={
                "work_item_id": str(item_id),
                "priority": priority,
                "expected_updated_at": expected.isoformat(),
            },
            operation=_change_priority,
        )

    except InvalidWorkItemRecordError:
        return fail(
            name=name,
            description="Change work-item priority.",
            code="INVALID_PRIORITY",
            message="The requested priority is invalid.",
            status=400,
            inputs=inputs,
        )
    except ActivityRelatedRecordNotFoundError:
        return fail(
            name=name,
            description="Change work-item priority.",
            code="RELATED_RECORD_NOT_FOUND",
            message="The work item or actor could not be found.",
            status=404,
            inputs=inputs,
        )
    except InvalidActivityRecordError:
        return fail(
            name=name,
            description="Change work-item priority.",
            code="ACTIVITY_WRITE_FAILED",
            message=(
                "The priority change was not committed because its activity "
                "event could not be recorded."
            ),
            status=500,
            inputs=inputs,
        )
    except (WorkItemDatabaseError, ActivityDatabaseError):
        return fail(
            name=name,
            description="Change work-item priority.",
            code="DATABASE_ERROR",
            message="The work-item priority could not be changed right now.",
            status=500,
            inputs=inputs,
        )