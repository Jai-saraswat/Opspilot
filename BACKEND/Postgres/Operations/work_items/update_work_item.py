"""Update basic work-item details."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any
from uuid import UUID

import psycopg
from psycopg import errors as pg_errors
from psycopg.rows import dict_row

from BACKEND.Postgres.Operations._db import (
    connection_scope,
    log_database_failure,
)
from BACKEND.Postgres.Operations.work_items.errors import (
    InvalidWorkItemRecordError,
    WorkItemDatabaseError,
)

logger = logging.getLogger(__name__)


class _Unset:
    """Distinguish an omitted argument from an explicitly supplied value."""


UNSET = _Unset()


def update_work_item(
    work_item_id: UUID,
    *,
    expected_updated_at: datetime,
    title: str | _Unset = UNSET,
    description: str | _Unset = UNSET,
    type: str | _Unset = UNSET,
    connection: psycopg.Connection | None = None,
) -> dict[str, Any] | None:
    """Update supplied details only.

    Returns None if the item is missing or updated_at no longer matches
    expected_updated_at. Services can retrieve the item to distinguish
    a missing item from a stale update.

    None is not accepted as a value for title, description, or type.
    """
    updates: list[str] = []
    parameters: list[Any] = []

    if not isinstance(title, _Unset):
        if title is None:
            raise InvalidWorkItemRecordError(
                "Title cannot be null."
            )
        updates.append("title = %s")
        parameters.append(title)

    if not isinstance(description, _Unset):
        if description is None:
            raise InvalidWorkItemRecordError(
                "Description cannot be null."
            )
        updates.append("description = %s")
        parameters.append(description)

    if not isinstance(type, _Unset):
        if type is None:
            raise InvalidWorkItemRecordError(
                "Work-item type cannot be null."
            )
        updates.append("type = %s")
        parameters.append(type)

    if not updates:
        raise InvalidWorkItemRecordError(
            "Provide at least one field to update."
        )

    # Use the statement's current wall-clock time for the update marker.
    updates.append("updated_at = clock_timestamp()")
    parameters.extend((work_item_id, expected_updated_at))

    query = f"""
        UPDATE work_items
        SET {", ".join(updates)}
        WHERE id = %s
          AND updated_at = %s
        RETURNING
            id,
            title,
            description,
            type,
            status,
            priority,
            team_id,
            created_by,
            assignee_id,
            created_at,
            updated_at,
            completed_at;
    """

    try:
        with connection_scope(connection) as conn:
            with conn.cursor(row_factory=dict_row) as cursor:
                cursor.execute(query, tuple(parameters))
                row = cursor.fetchone()

                return dict(row) if row is not None else None

    except pg_errors.CheckViolation as exc:
        log_database_failure(logger, "update_work_item", exc)
        raise InvalidWorkItemRecordError(
            "One or more work-item fields are invalid."
        ) from None

    except (psycopg.Error, RuntimeError) as exc:
        log_database_failure(logger, "update_work_item", exc)
        raise WorkItemDatabaseError(
            "Unable to update the work item right now."
        ) from None