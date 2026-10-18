"""Change work-item status and record the change atomically."""

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
from BACKEND.Postgres.Operations.work_items.update_work_item_status import (
    update_work_item_status,
)
from BACKEND.Services.idempotency import execute_idempotently
from BACKEND.Services.work_management._common import (
    active_actor,
    can_manage_team,
    can_view_team,
    fail,
    is_team_member,
    parse_identifier,
    public_work_item,
    record_work_item_activity,
    success,
)
from BACKEND.Services.work_management.update_work_item import (
    _parse_expected_timestamp,
)

ALLOWED_TRANSITIONS = {
    "open": {"in_progress", "cancelled"},
    "in_progress": {"open", "resolved", "cancelled"},
    "pending_approval": {"cancelled"},
    "resolved": {"in_progress"},
    "cancelled": set(),
}
VALID_STATUSES = set(ALLOWED_TRANSITIONS)


def change_work_item_status(
    *,
    actor_user_id: UUID | str,
    work_item_id: UUID | str,
    status: str,
    expected_updated_at: datetime | str,
    idempotency_key: str | None = None,
):
    name = "change_work_item_status"
    inputs = {
        "work_item_id": str(work_item_id),
        "status": status,
    }

    actor_id = active_actor(actor_user_id)
    if actor_id is None:
        return fail(
            name=name,
            description="Change a work item's status.",
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
            description="Change a work item's status.",
            code="INVALID_INPUT",
            message="Provide a valid UUID and timezone-aware timestamp.",
            status=400,
            inputs=inputs,
        )

    if status not in VALID_STATUSES:
        return fail(
            name=name,
            description="Change a work item's status.",
            code="INVALID_STATUS",
            message=f"Status must be one of: {', '.join(sorted(VALID_STATUSES))}.",
            status=400,
            inputs=inputs,
        )

    if status == "pending_approval":
        return fail(
            name=name,
            description="Change a work item's status.",
            code="APPROVAL_FLOW_REQUIRED",
            message="The approval workflow is not implemented yet.",
            status=409,
            inputs=inputs,
        )

    try:
        def _change_status(connection):
            current = get_work_item_by_id(
                item_id,
                connection=connection,
            )

            if current is None:
                return fail(
                    name=name,
                    description="Change a work item's status.",
                    code="WORK_ITEM_NOT_FOUND",
                    message="The work item does not exist.",
                    status=404,
                    inputs=inputs,
                )

            team_id = current["team_id"]

            if not can_view_team(actor_id, team_id):
                return fail(
                    name=name,
                    description="Change a work item's status.",
                    code="FORBIDDEN",
                    message="You cannot access this work item.",
                    status=403,
                    inputs=inputs,
                )

            is_member = is_team_member(team_id, actor_id)
            can_manage = can_manage_team(
                actor_id,
                team_id,
                "work_items:status:any",
            )
            is_assignee = (
                is_member and current.get("assignee_id") == actor_id
            )
            may_cancel_own_open_item = (
                is_member
                and current.get("created_by") == actor_id
                and status == "cancelled"
                and current["status"] == "open"
            )

            if not (
                can_manage
                or is_assignee
                or may_cancel_own_open_item
            ):
                return fail(
                    name=name,
                    description="Change a work item's status.",
                    code="FORBIDDEN",
                    message=(
                        "You are not authorized to change this item's status."
                    ),
                    status=403,
                    inputs=inputs,
                )

            previous_status = current["status"]

            if status not in ALLOWED_TRANSITIONS[previous_status]:
                return fail(
                    name=name,
                    description="Change a work item's status.",
                    code="INVALID_TRANSITION",
                    message=(
                        f"The transition from '{previous_status}' "
                        f"to '{status}' is not allowed."
                    ),
                    status=409,
                    inputs=inputs,
                )

            if current["type"] == "approval" and status == "resolved":
                return fail(
                    name=name,
                    description="Change a work item's status.",
                    code="APPROVAL_FLOW_REQUIRED",
                    message=(
                        "Approval-type work items must be resolved "
                        "through the approval workflow."
                    ),
                    status=409,
                    inputs=inputs,
                )

            updated = update_work_item_status(
                item_id,
                status,
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
                        description="Change a work item's status.",
                        code="WORK_ITEM_NOT_FOUND",
                        message="The work item no longer exists.",
                        status=404,
                        inputs=inputs,
                    )

                return fail(
                    name=name,
                    description="Change a work item's status.",
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
                action="status_changed",
                details={
                    "old_status": previous_status,
                    "new_status": updated["status"],
                },
            )

            return success(
                name=name,
                description="Work-item status updated.",
                data={"work_item": public_work_item(updated)},
                inputs=inputs,
            )

        return execute_idempotently(
            user_id=actor_id,
            idempotency_key=idempotency_key,
            operation_name=name,
            category="work_management",
            subcategory="work_items",
            description="Change a work item's status.",
            payload={
                "work_item_id": str(item_id),
                "status": status,
                "expected_updated_at": expected.isoformat(),
            },
            operation=_change_status,
        )

    except InvalidWorkItemRecordError:
        return fail(
            name=name,
            description="Change a work item's status.",
            code="INVALID_STATUS",
            message="The requested status is invalid.",
            status=400,
            inputs=inputs,
        )
    except ActivityRelatedRecordNotFoundError:
        return fail(
            name=name,
            description="Change a work item's status.",
            code="RELATED_RECORD_NOT_FOUND",
            message="The work item or actor could not be found.",
            status=404,
            inputs=inputs,
        )
    except InvalidActivityRecordError:
        return fail(
            name=name,
            description="Change a work item's status.",
            code="ACTIVITY_WRITE_FAILED",
            message=(
                "The status change was not committed because its "
                "activity event could not be recorded."
            ),
            status=500,
            inputs=inputs,
        )
    except (WorkItemDatabaseError, ActivityDatabaseError):
        return fail(
            name=name,
            description="Change a work item's status.",
            code="DATABASE_ERROR",
            message="The work-item status could not be changed right now.",
            status=500,
            inputs=inputs,
        )