"""Shared helpers for activity-history Services."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from BACKEND.Services.contracts import service_failure, service_success
from BACKEND.Services.work_management._common import (
    active_actor,
    parse_identifier,
)


def success(
    *,
    name: str,
    description: str,
    data: Any,
    inputs: dict[str, Any] | None = None,
    status: int = 200,
):
    return service_success(
        name=name,
        category="activity",
        subcategory="activity_history",
        description=description,
        inputs=inputs or {},
        data=data,
        http_status=status,
    )


def fail(
    *,
    name: str,
    description: str,
    code: str,
    message: str,
    status: int,
    inputs: dict[str, Any] | None = None,
):
    return service_failure(
        name=name,
        category="activity",
        subcategory="activity_history",
        description=description,
        code=code,
        message=message,
        http_status=status,
        inputs=inputs or {},
    )


def serialize_value(value: Any) -> Any:
    """Convert PostgreSQL values into JSON-friendly values."""
    if isinstance(value, UUID):
        return str(value)

    if isinstance(value, (datetime, date)):
        return value.isoformat()

    if isinstance(value, dict):
        return {
            str(key): serialize_value(item)
            for key, item in value.items()
        }

    if isinstance(value, list):
        return [serialize_value(item) for item in value]

    return value


def public_activity(activity: dict[str, Any]) -> dict[str, Any]:
    """Expose only the fields belonging to the activity schema."""
    allowed = (
        "id",
        "work_item_id",
        "actor_id",
        "action",
        "details",
        "created_at",
    )

    return {
        key: serialize_value(activity[key])
        for key in allowed
        if key in activity
    }


def public_activities(
    activities: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [public_activity(item) for item in activities]


def valid_pagination(limit: int, offset: int) -> bool:
    """Match activity Operation limits."""
    return (
        isinstance(limit, int)
        and not isinstance(limit, bool)
        and 1 <= limit <= 100
        and isinstance(offset, int)
        and not isinstance(offset, bool)
        and offset >= 0
    )


__all__ = [
    "active_actor",
    "fail",
    "parse_identifier",
    "public_activities",
    "public_activity",
    "success",
    "valid_pagination",
]