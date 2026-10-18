"""Update a work item's status with stale-update protection."""

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


def update_work_item_status(
    work_item_id: UUID,
    status: str,
    *,
    expected_updated_at: datetime,
    connection: psycopg.Connection | None = None,
) -> dict[str, Any] | None:
    """Update status if the supplied updated_at still matches.

    Returns None if the work item is missing or has changed since it was read.
    """
    query = """
        UPDATE work_items
        SET
            status = %s,
            completed_at = CASE
                WHEN %s = 'resolved'
                    THEN COALESCE(completed_at, clock_timestamp())
                ELSE NULL
            END,
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
                    (status, status, work_item_id, expected_updated_at),
                )
                row = cursor.fetchone()

                return dict(row) if row is not None else None

    except pg_errors.CheckViolation as exc:
        log_database_failure(logger, "update_work_item_status", exc)
        raise InvalidWorkItemRecordError(
            "The supplied work-item status is invalid."
        ) from None

    except (psycopg.Error, RuntimeError) as exc:
        log_database_failure(logger, "update_work_item_status", exc)
        raise WorkItemDatabaseError(
            "Unable to update the work-item status right now."
        ) from None