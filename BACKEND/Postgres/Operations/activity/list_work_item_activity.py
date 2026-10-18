"""List activity history for a work item."""

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


def list_work_item_activity(
    work_item_id: UUID,
    *,
    limit: int = 50,
    offset: int = 0,
    action: str | None = None,
    connection: psycopg.Connection | None = None,
) -> dict[str, Any]:
    """Return a paginated activity history for a work item."""
    if not 1 <= limit <= 100:
        raise ValueError("Limit must be between 1 and 100.")

    if offset < 0:
        raise ValueError("Offset cannot be negative.")

    conditions = ["work_item_id = %s"]
    parameters: list[Any] = [work_item_id]

    if action is not None:
        conditions.append("action = %s")
        parameters.append(action)

    where_clause = "WHERE " + " AND ".join(conditions)

    count_query = f"""
        SELECT COUNT(*) AS total
        FROM work_item_activity
        {where_clause};
    """

    list_query = f"""
        SELECT
            id,
            work_item_id,
            actor_id,
            action,
            details,
            created_at
        FROM work_item_activity
        {where_clause}
        ORDER BY created_at DESC, id DESC
        LIMIT %s OFFSET %s;
    """

    try:
        with connection_scope(connection) as conn:
            with conn.cursor(row_factory=dict_row) as cursor:
                cursor.execute(count_query, tuple(parameters))
                total = cursor.fetchone()["total"]

                cursor.execute(
                    list_query,
                    (*parameters, limit, offset),
                )
                rows = cursor.fetchall()

                return {
                    "items": [dict(row) for row in rows],
                    "total": total,
                    "limit": limit,
                    "offset": offset,
                }

    except (psycopg.Error, RuntimeError) as exc:
        log_database_failure(logger, "list_work_item_activity", exc)
        raise ActivityDatabaseError(
            "Unable to retrieve work-item history right now."
        ) from None