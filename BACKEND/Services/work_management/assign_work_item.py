"""Assign or unassign a work item and record the change atomically."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from BACKEND.Postgres.Operations.activity.errors import (
    ActivityDatabaseError,
    ActivityRelatedRecordNotFoundError,
    InvalidActivityRecordError,
)
from BACKEND.Postgres.Operations.work_items.assign_work_item import (
    assign_work_item as assign_work_item_operation,
)
from BACKEND.Postgres.Operations.work_items.errors import (
    WorkItemDatabaseError,
    WorkItemRelatedRecordNotFoundError,
)
from BACKEND.Postgres.Operations.work_items.get_work_item_by_id import (
    get_work_item_by_id,
)
from BACKEND.Services.idempotency import execute_idempotently
from BACKEND.Services.work_management._common import (
    active_actor,
    active_user_in_team,
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


def assign_work_item(
    *,
    actor_user_id: UUID | str,
    work_item_id: UUID | str,
    assignee_id: UUID | str | None,
    expected_updated_at: datetime | str,
    idempotency_key: str | None = None,
):
    """Assign, reassign, or unassign an item and audit the change."""
    name = "assign_work_item"
    inputs = {"work_item_id": str(work_item_id)}

    actor_id = active_actor(actor_user_id)
    if actor_id is None:
        return fail(
            name=name,
            description="Assign a work item.",
            code="UNAUTHENTICATED",
            message="An active user account is required.",
            status=401,
            inputs=inputs,
        )

    try:
        item_id = parse_identifier(work_item_id)
        expected = _parse_expected_timestamp(expected_updated_at)
        target_id = (
            parse_identifier(assignee_id)
            if assignee_id is not None
            else None
        )
    except (ValueError, TypeError, AttributeError):
        return fail(
            name=name,
            description="Assign a work item.",
            code="INVALID_INPUT",
            message=(
                "Provide valid identifiers and a timezone-aware "
                "expected_updated_at timestamp."
            ),
            status=400,
            inputs=inputs,
        )

    try:
        def _assign(connection):
            current = get_work_item_by_id(
                item_id,
                connection=connection,
            )

            if current is None:
                return fail(
                    name=name,
                    description="Assign a work item.",
                    code="WORK_ITEM_NOT_FOUND",
                    message="The work item does not exist.",
                    status=404,
                    inputs=inputs,
                )

            team_id = current["team_id"]

            if not can_view_team(actor_id, team_id):
                return fail(
                    name=name,
                    description="Assign a work item.",
                    code="FORBIDDEN",
                    message="You cannot access this work item.",
                    status=403,
                    inputs=inputs,
                )

            if not can_manage_team(
                actor_id,
                team_id,
                "work_items:assign:any",
            ):
                return fail(
                    name=name,
                    description="Assign a work item.",
                    code="FORBIDDEN",
                    message=(
                        "Only team leads or explicitly authorized "
                        "managers may assign work."
                    ),
                    status=403,
                    inputs=inputs,
                )

            if (
                target_id is not None
                and not active_user_in_team(target_id, team_id)
            ):
                return fail(
                    name=name,
                    description="Assign a work item.",
                    code="INVALID_ASSIGNEE",
                    message=(
                        "The assignee must be an active member of "
                        "the work item's team."
                    ),
                    status=400,
                    inputs=inputs,
                )

            old_assignee = current.get("assignee_id")

            if old_assignee == target_id:
                if current["updated_at"] != expected:
                    return fail(
                        name=name,
                        description="Assign a work item.",
                        code="STALE_WORK_ITEM",
                        message=(
                            "The work item changed since you last read it. "
                            "Retrieve the latest version and retry."
                        ),
                        status=409,
                        inputs=inputs,
                    )

                return success(
                    name=name,
                    description=(
                        "The work item already has the requested assignment."
                    ),
                    data={"work_item": public_work_item(current)},
                    inputs=inputs,
                )

            updated = assign_work_item_operation(
                item_id,
                target_id,
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
                        description="Assign a work item.",
                        code="WORK_ITEM_NOT_FOUND",
                        message="The work item no longer exists.",
                        status=404,
                        inputs=inputs,
                    )

                return fail(
                    name=name,
                    description="Assign a work item.",
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
                action="assignee_changed",
                details={
                    "old_assignee_id": (
                        str(old_assignee)
                        if old_assignee is not None
                        else None
                    ),
                    "new_assignee_id": (
                        str(target_id)
                        if target_id is not None
                        else None
                    ),
                },
            )

            return success(
                name=name,
                description="Work item assignment updated.",
                data={"work_item": public_work_item(updated)},
                inputs=inputs,
            )

        return execute_idempotently(
            user_id=actor_id,
            idempotency_key=idempotency_key,
            operation_name=name,
            category="work_management",
            subcategory="work_items",
            description="Assign a work item.",
            payload={
                "work_item_id": str(item_id),
                "assignee_id": (
                    str(target_id) if target_id is not None else None
                ),
                "expected_updated_at": expected.isoformat(),
            },
            operation=_assign,
        )

    except WorkItemRelatedRecordNotFoundError:
        return fail(
            name=name,
            description="Assign a work item.",
            code="RELATED_RECORD_NOT_FOUND",
            message="The work item or assignee could not be found.",
            status=404,
            inputs=inputs,
        )
    except ActivityRelatedRecordNotFoundError:
        return fail(
            name=name,
            description="Assign a work item.",
            code="RELATED_RECORD_NOT_FOUND",
            message="The work item or activity actor could not be found.",
            status=404,
            inputs=inputs,
        )
    except InvalidActivityRecordError:
        return fail(
            name=name,
            description="Assign a work item.",
            code="ACTIVITY_WRITE_FAILED",
            message=(
                "The assignment was not committed because its activity "
                "event could not be recorded."
            ),
            status=500,
            inputs=inputs,
        )
    except (WorkItemDatabaseError, ActivityDatabaseError):
        return fail(
            name=name,
            description="Assign a work item.",
            code="DATABASE_ERROR",
            message="The work item could not be assigned right now.",
            status=500,
            inputs=inputs,
        )