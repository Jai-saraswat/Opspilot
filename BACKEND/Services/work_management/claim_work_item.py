"""Claim an unassigned work item and record the claim atomically."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from BACKEND.Postgres.Operations.activity.errors import (
    ActivityDatabaseError,
    ActivityRelatedRecordNotFoundError,
    InvalidActivityRecordError,
)
from BACKEND.Postgres.Operations.work_items.claim_work_item_if_unassigned import (
    claim_work_item_if_unassigned,
)
from BACKEND.Postgres.Operations.work_items.errors import WorkItemDatabaseError
from BACKEND.Postgres.Operations.work_items.get_work_item_by_id import (
    get_work_item_by_id,
)
from BACKEND.Services.idempotency import execute_idempotently
from BACKEND.Services.work_management._common import (
    active_actor,
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


def claim_work_item(
    *,
    actor_user_id: UUID | str,
    work_item_id: UUID | str,
    expected_updated_at: datetime | str,
    idempotency_key: str | None = None,
):
    name = "claim_work_item"
    inputs = {"work_item_id": str(work_item_id)}

    actor_id = active_actor(actor_user_id)
    if actor_id is None:
        return fail(
            name=name,
            description="Claim an unassigned work item.",
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
            description="Claim an unassigned work item.",
            code="INVALID_INPUT",
            message="Provide a valid UUID and timezone-aware timestamp.",
            status=400,
            inputs=inputs,
        )

    try:
        def _claim(connection):
            current = get_work_item_by_id(
                item_id,
                connection=connection,
            )

            if current is None:
                return fail(
                    name=name,
                    description="Claim an unassigned work item.",
                    code="WORK_ITEM_NOT_FOUND",
                    message="The work item does not exist.",
                    status=404,
                    inputs=inputs,
                )

            team_id = current["team_id"]

            if (
                not can_view_team(actor_id, team_id)
                or not is_team_member(team_id, actor_id)
            ):
                return fail(
                    name=name,
                    description="Claim an unassigned work item.",
                    code="FORBIDDEN",
                    message=(
                        "You must be a current team member to claim "
                        "this work item."
                    ),
                    status=403,
                    inputs=inputs,
                )

            if current.get("assignee_id") is not None:
                return fail(
                    name=name,
                    description="Claim an unassigned work item.",
                    code="ALREADY_ASSIGNED",
                    message="This work item already has an assignee.",
                    status=409,
                    inputs=inputs,
                )

            claimed = claim_work_item_if_unassigned(
                item_id,
                actor_id,
                expected_updated_at=expected,
                connection=connection,
            )

            if claimed is None:
                latest = get_work_item_by_id(
                    item_id,
                    connection=connection,
                )

                if latest is None:
                    return fail(
                        name=name,
                        description="Claim an unassigned work item.",
                        code="WORK_ITEM_NOT_FOUND",
                        message="The work item no longer exists.",
                        status=404,
                        inputs=inputs,
                    )

                if latest.get("assignee_id") is not None:
                    return fail(
                        name=name,
                        description="Claim an unassigned work item.",
                        code="ALREADY_ASSIGNED",
                        message="Another request claimed this work item first.",
                        status=409,
                        inputs=inputs,
                    )

                return fail(
                    name=name,
                    description="Claim an unassigned work item.",
                    code="STALE_WORK_ITEM",
                    message=(
                        "The work item changed. Retrieve its latest "
                        "version and retry."
                    ),
                    status=409,
                    inputs=inputs,
                )

            record_work_item_activity(
                connection=connection,
                work_item_id=item_id,
                actor_id=actor_id,
                action="work_item_claimed",
                details={
                    "previous_assignee_id": None,
                    "new_assignee_id": str(actor_id),
                },
            )

            return success(
                name=name,
                description="Work item claimed.",
                data={"work_item": public_work_item(claimed)},
                inputs=inputs,
            )

        return execute_idempotently(
            user_id=actor_id,
            idempotency_key=idempotency_key,
            operation_name=name,
            category="work_management",
            subcategory="work_items",
            description="Claim an unassigned work item.",
            payload={
                "work_item_id": str(item_id),
                "expected_updated_at": expected.isoformat(),
            },
            operation=_claim,
        )

    except ActivityRelatedRecordNotFoundError:
        return fail(
            name=name,
            description="Claim an unassigned work item.",
            code="RELATED_RECORD_NOT_FOUND",
            message="The work item or actor could not be found.",
            status=404,
            inputs=inputs,
        )
    except InvalidActivityRecordError:
        return fail(
            name=name,
            description="Claim an unassigned work item.",
            code="ACTIVITY_WRITE_FAILED",
            message=(
                "The claim was not committed because its activity "
                "event could not be recorded."
            ),
            status=500,
            inputs=inputs,
        )
    except (WorkItemDatabaseError, ActivityDatabaseError):
        return fail(
            name=name,
            description="Claim an unassigned work item.",
            code="DATABASE_ERROR",
            message="The work item could not be claimed right now.",
            status=500,
            inputs=inputs,
        )