"""Retrieve an activity record by UUID."""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

from BACKEND.Postgres.Operations._db import (
    connection_scope,
    log_database_failure,
)
from BACKEND.Postgres.Operations.activity.errors import ActivityDatabaseError

logger = logging.getLogger(__name__)


def get_activity_by_id(
    activity_id: UUID,
    *,
    connection: psycopg.Connection | None = None,
) -> dict[str, Any] | None:
    """Return the activity record, or None if it does not exist."""
    query = """
        SELECT
            id,
            work_item_id,
            actor_id,
            action,
            details,
            created_at
        FROM work_item_activity
        WHERE id = %s;
    """

    try:
        with connection_scope(connection) as conn:
            with conn.cursor(row_factory=dict_row) as cursor:
                cursor.execute(query, (activity_id,))
                row = cursor.fetchone()

                return dict(row) if row is not None else None

    except (psycopg.Error, RuntimeError) as exc:
        log_database_failure(logger, "get_activity_by_id", exc)
        raise ActivityDatabaseError(
            "Unable to retrieve the activity record right now."
        ) from None