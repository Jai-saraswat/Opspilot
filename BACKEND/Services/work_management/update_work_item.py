"""Update work-item details and record the change atomically."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
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
from BACKEND.Postgres.Operations.work_items.update_work_item import (
    UNSET,
    update_work_item as update_work_item_operation,
)
from BACKEND.Services.idempotency import execute_idempotently
from BACKEND.Services.work_management._common import (
    active_actor,
    can_edit_item,
    fail,
    parse_identifier,
    public_work_item,
    record_work_item_activity,
    success,
)

VALID_TYPES = {"investigation", "action", "incident", "approval"}


def _parse_expected_timestamp(value: datetime | str) -> datetime:
    """Require a timezone-aware timestamp without discarding precision."""
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))

    if not isinstance(value, datetime):
        raise ValueError(
            "expected_updated_at must be a datetime or ISO timestamp."
        )

    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(
            "expected_updated_at must include a timezone."
        )

    return value


def _json_value(value: Any) -> Any:
    """Convert dates and UUIDs to stable activity-detail values."""
    if isinstance(value, UUID):
        return str(value)

    if isinstance(value, (datetime, date)):
        return value.isoformat()

    return value


def update_work_item(
    *,
    actor_user_id: UUID | str,
    work_item_id: UUID | str,
    expected_updated_at: datetime | str,
    title: str | None = None,
    description: str | None = None,
    type: str | None = None,
    idempotency_key: str | None = None,
):
    """Update supported fields and insert activity in one transaction."""
    name = "update_work_item"
    inputs = {"work_item_id": str(work_item_id)}

    actor_id = active_actor(actor_user_id)
    if actor_id is None:
        return fail(
            name=name,
            description="Update work-item details.",
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
            description="Update work-item details.",
            code="INVALID_INPUT",
            message=(
                "Provide a valid work-item UUID and a timezone-aware "
                "expected_updated_at timestamp."
            ),
            status=400,
            inputs=inputs,
        )

    updates: dict[str, Any] = {}

    if title is not None:
        if (
            not isinstance(title, str)
            or not title.strip()
            or len(title.strip()) > 200
        ):
            return fail(
                name=name,
                description="Update work-item details.",
                code="INVALID_TITLE",
                message="Title must contain 1–200 characters.",
                status=400,
                inputs=inputs,
            )
        updates["title"] = title.strip()

    if description is not None:
        if not isinstance(description, str) or not description.strip():
            return fail(
                name=name,
                description="Update work-item details.",
                code="INVALID_DESCRIPTION",
                message="Description must not be empty.",
                status=400,
                inputs=inputs,
            )
        updates["description"] = description.strip()

    if type is not None:
        if type not in VALID_TYPES:
            return fail(
                name=name,
                description="Update work-item details.",
                code="INVALID_TYPE",
                message=(
                    f"Type must be one of: {', '.join(sorted(VALID_TYPES))}."
                ),
                status=400,
                inputs=inputs,
            )
        updates["type"] = type

    if not updates:
        return fail(
            name=name,
            description="Update work-item details.",
            code="EMPTY_UPDATE",
            message="Provide at least one field to update.",
            status=400,
            inputs=inputs,
        )

    try:
        def _update(connection):
            current = get_work_item_by_id(
                item_id,
                connection=connection,
            )

            if current is None:
                return fail(
                    name=name,
                    description="Update work-item details.",
                    code="WORK_ITEM_NOT_FOUND",
                    message="The work item does not exist.",
                    status=404,
                    inputs=inputs,
                )

            if not can_edit_item(actor_id, current):
                return fail(
                    name=name,
                    description="Update work-item details.",
                    code="FORBIDDEN",
                    message="You cannot edit this work item.",
                    status=403,
                    inputs=inputs,
                )

            activity_details: dict[str, Any] = {}

            for field, new_value in updates.items():
                old_value = current.get(field)
                if old_value != new_value:
                    activity_details[field] = {
                        "old": _json_value(old_value),
                        "new": _json_value(new_value),
                    }

            if not activity_details:
                if current["updated_at"] != expected:
                    return fail(
                        name=name,
                        description="Update work-item details.",
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
                    description="No work-item details changed.",
                    data={"work_item": public_work_item(current)},
                    inputs=inputs,
                )

            updated = update_work_item_operation(
                item_id,
                expected_updated_at=expected,
                title=updates.get("title", UNSET),
                description=updates.get("description", UNSET),
                type=updates.get("type", UNSET),
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
                        description="Update work-item details.",
                        code="WORK_ITEM_NOT_FOUND",
                        message="The work item no longer exists.",
                        status=404,
                        inputs=inputs,
                    )

                return fail(
                    name=name,
                    description="Update work-item details.",
                    code="STALE_WORK_ITEM",
                    message=(
                        "The work item changed since you last read it. "
                        "Retrieve the latest version and retry."
                    ),
                    status=409,
                    inputs=inputs,
                )

            record_work_item_activity(
                connection=connection,
                work_item_id=item_id,
                actor_id=actor_id,
                action="work_item_updated",
                details=activity_details,
            )

            return success(
                name=name,
                description="Work-item details updated.",
                data={"work_item": public_work_item(updated)},
                inputs=inputs,
            )

        return execute_idempotently(
            user_id=actor_id,
            idempotency_key=idempotency_key,
            operation_name=name,
            category="work_management",
            subcategory="work_items",
            description="Update work-item details.",
            payload={
                "work_item_id": str(item_id),
                "expected_updated_at": expected.isoformat(),
                "title": updates.get("title"),
                "description": updates.get("description"),
                "type": updates.get("type"),
            },
            operation=_update,
        )

    except InvalidWorkItemRecordError:
        return fail(
            name=name,
            description="Update work-item details.",
            code="INVALID_WORK_ITEM",
            message="One or more work-item fields are invalid.",
            status=400,
            inputs=inputs,
        )
    except ActivityRelatedRecordNotFoundError:
        return fail(
            name=name,
            description="Update work-item details.",
            code="RELATED_RECORD_NOT_FOUND",
            message="The work item or activity actor could not be found.",
            status=404,
            inputs=inputs,
        )
    except InvalidActivityRecordError:
        return fail(
            name=name,
            description="Update work-item details.",
            code="ACTIVITY_WRITE_FAILED",
            message=(
                "The update was not committed because its activity "
                "event could not be recorded."
            ),
            status=500,
            inputs=inputs,
        )
    except (WorkItemDatabaseError, ActivityDatabaseError):
        return fail(
            name=name,
            description="Update work-item details.",
            code="DATABASE_ERROR",
            message="The work item could not be updated right now.",
            status=500,
            inputs=inputs,
        )