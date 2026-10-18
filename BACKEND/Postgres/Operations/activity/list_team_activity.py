"""List activity for work items belonging to a team."""

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


def list_team_activity(
    team_id: UUID,
    *,
    limit: int = 50,
    offset: int = 0,
    action: str | None = None,
    connection: psycopg.Connection | None = None,
) -> dict[str, Any]:
    """Return a paginated activity feed for a team."""
    if not 1 <= limit <= 100:
        raise ValueError("Limit must be between 1 and 100.")

    if offset < 0:
        raise ValueError("Offset cannot be negative.")

    conditions = ["wi.team_id = %s"]
    parameters: list[Any] = [team_id]

    if action is not None:
        conditions.append("a.action = %s")
        parameters.append(action)

    where_clause = "WHERE " + " AND ".join(conditions)

    count_query = f"""
        SELECT COUNT(*) AS total
        FROM work_item_activity AS a
        JOIN work_items AS wi
          ON wi.id = a.work_item_id
        {where_clause};
    """

    list_query = f"""
        SELECT
            a.id,
            a.work_item_id,
            a.actor_id,
            a.action,
            a.details,
            a.created_at
        FROM work_item_activity AS a
        JOIN work_items AS wi
          ON wi.id = a.work_item_id
        {where_clause}
        ORDER BY a.created_at DESC, a.id DESC
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
        log_database_failure(logger, "list_team_activity", exc)
        raise ActivityDatabaseError(
            "Unable to retrieve team activity right now."
        ) from None