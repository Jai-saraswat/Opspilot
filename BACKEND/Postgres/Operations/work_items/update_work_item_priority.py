"""Update work-item priority with stale-update protection."""

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


def update_work_item_priority(
    work_item_id: UUID,
    priority: str,
    *,
    expected_updated_at: datetime,
    connection: psycopg.Connection | None = None,
) -> dict[str, Any] | None:
    """Update priority if the supplied updated_at still matches.

    Returns None if the item is missing or has changed since it was read.
    """
    query = """
        UPDATE work_items
        SET
            priority = %s,
            updated_at = clock_timestamp()
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
                cursor.execute(
                    query,
                    (priority, work_item_id, expected_updated_at),
                )
                row = cursor.fetchone()

                return dict(row) if row is not None else None

    except pg_errors.CheckViolation as exc:
        log_database_failure(logger, "update_work_item_priority", exc)
        raise InvalidWorkItemRecordError(
            "The supplied priority is invalid."
        ) from None

    except (psycopg.Error, RuntimeError) as exc:
        log_database_failure(logger, "update_work_item_priority", exc)
        raise WorkItemDatabaseError(
            "Unable to update the work-item priority right now."
        ) from None