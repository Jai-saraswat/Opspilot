"""Atomically claim an unassigned work item."""

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
    WorkItemDatabaseError,
    WorkItemRelatedRecordNotFoundError,
)

logger = logging.getLogger(__name__)


def claim_work_item_if_unassigned(
    work_item_id: UUID,
    assignee_id: UUID,
    *,
    expected_updated_at: datetime,
    connection: psycopg.Connection | None = None,
) -> dict[str, Any] | None:
    """Claim only when the item remains unassigned and unchanged.

    Returns None if the item is missing, already assigned, or stale.
    The service must validate that the assignee is a member of the team.
    """
    query = """
        UPDATE work_items
        SET
            assignee_id = %s,
            updated_at = clock_timestamp()
        WHERE id = %s
          AND assignee_id IS NULL
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
                    (assignee_id, work_item_id, expected_updated_at),
                )
                row = cursor.fetchone()

                return dict(row) if row is not None else None

    except pg_errors.ForeignKeyViolation as exc:
        if exc.diag.constraint_name == "work_items_assignee_id_fkey":
            raise WorkItemRelatedRecordNotFoundError(
                "The specified assignee does not exist."
            ) from None

        log_database_failure(
            logger,
            "claim_work_item_if_unassigned",
            exc,
        )
        raise WorkItemDatabaseError(
            "Unable to claim the work item right now."
        ) from None

    except (psycopg.Error, RuntimeError) as exc:
        log_database_failure(
            logger,
            "claim_work_item_if_unassigned",
            exc,
        )
        raise WorkItemDatabaseError(
            "Unable to claim the work item right now."
        ) from None