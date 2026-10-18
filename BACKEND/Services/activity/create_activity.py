"""Create an activity record from a trusted backend workflow."""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

import psycopg

from BACKEND.Postgres.Operations.activity.create_activity import (
    create_activity as create_activity_operation,
)
from BACKEND.Postgres.Operations.activity.errors import (
    ActivityDatabaseError,
    ActivityRelatedRecordNotFoundError,
    InvalidActivityRecordError,
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
from BACKEND.Services.idempotency import execute_idempotently
from BACKEND.Services.work_management._common import (
    can_manage_team,
    is_team_member,
)


def create_activity(
    *,
    actor_user_id: UUID | str,
    work_item_id: UUID | str,
    action: str,
    details: dict[str, Any] | None = None,
    connection: psycopg.Connection | None = None,
    idempotency_key: str | None = None,
):
    """Create activity after checking access to the work item.

    When called inside a caller-owned transaction, provide connection and
    omit idempotency_key. The caller then owns rollback behavior.

    Standalone calls use the centralized idempotency Service.
    """
    name = "create_activity"
    description = "Create a work-item activity record."
    inputs = {
        "work_item_id": str(work_item_id),
        "action": action if isinstance(action, str) else None,
    }

    actor_id = active_actor(actor_user_id)

    if actor_id is None:
        return fail(
            name=name,
            description=description,
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
            description=description,
            code="INVALID_WORK_ITEM_ID",
            message="The work-item identifier is invalid.",
            status=400,
            inputs=inputs,
        )

    if (
        not isinstance(action, str)
        or not action.strip()
        or len(action.strip()) > 50
    ):
        return fail(
            name=name,
            description=description,
            code="INVALID_ACTION",
            message="Action must contain 1–50 characters.",
            status=400,
            inputs=inputs,
        )

    action = action.strip()
    details = {} if details is None else details

    if not isinstance(details, dict):
        return fail(
            name=name,
            description=description,
            code="INVALID_DETAILS",
            message="Activity details must be a JSON object.",
            status=400,
            inputs=inputs,
        )

    try:
        json.dumps(details, allow_nan=False)
    except (TypeError, ValueError, OverflowError):
        return fail(
            name=name,
            description=description,
            code="INVALID_DETAILS",
            message="Activity details must contain valid JSON data.",
            status=400,
            inputs=inputs,
        )

    if connection is not None and idempotency_key is not None:
        return fail(
            name=name,
            description=description,
            code="IDEMPOTENCY_EXTERNAL_CONNECTION_UNSUPPORTED",
            message=(
                "Do not combine an externally managed transaction with "
                "an idempotency key. Let the parent Service manage both."
            ),
            status=400,
            inputs=inputs,
        )

    def _create(active_connection):
        item = get_work_item_by_id(
            item_id,
            connection=active_connection,
        )

        if item is None:
            return fail(
                name=name,
                description=description,
                code="WORK_ITEM_NOT_FOUND",
                message="The work item does not exist.",
                status=404,
                inputs=inputs,
            )

        team_id = item["team_id"]

        allowed = (
            is_team_member(team_id, actor_id)
            or can_manage_team(
                actor_id,
                team_id,
                "work_items:manage:any",
            )
        )

        if not allowed:
            return fail(
                name=name,
                description=description,
                code="FORBIDDEN",
                message=(
                    "You are not authorized to record activity "
                    "for this work item."
                ),
                status=403,
                inputs=inputs,
            )

        record = create_activity_operation(
            work_item_id=item_id,
            actor_id=actor_id,
            action=action,
            details=details,
            connection=active_connection,
        )

        return success(
            name=name,
            description="Activity record created.",
            data={"activity": public_activity(record)},
            status=201,
            inputs=inputs,
        )

    try:
        if connection is not None:
            # Preserve caller-owned transactions for internal workflows.
            return _create(connection)

        return execute_idempotently(
            user_id=actor_id,
            idempotency_key=idempotency_key,
            operation_name=name,
            category="activity",
            subcategory="activity_history",
            description=description,
            payload={
                "work_item_id": str(item_id),
                "action": action,
                "details": details,
            },
            operation=_create,
        )

    except InvalidActivityRecordError:
        return fail(
            name=name,
            description=description,
            code="INVALID_ACTIVITY",
            message="The activity data violates a database constraint.",
            status=400,
            inputs=inputs,
        )
    except ActivityRelatedRecordNotFoundError:
        return fail(
            name=name,
            description=description,
            code="RELATED_RECORD_NOT_FOUND",
            message="The work item or actor no longer exists.",
            status=404,
            inputs=inputs,
        )
    except (ActivityDatabaseError, WorkItemDatabaseError):
        return fail(
            name=name,
            description=description,
            code="DATABASE_ERROR",
            message="The activity record could not be created right now.",
            status=500,
            inputs=inputs,
        )