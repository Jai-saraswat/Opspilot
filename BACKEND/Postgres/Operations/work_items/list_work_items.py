"""List work items with server-side pagination and filtering."""

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
from BACKEND.Postgres.Operations.work_items.errors import WorkItemDatabaseError

logger = logging.getLogger(__name__)


def list_work_items(
    *,
    limit: int = 50,
    offset: int = 0,
    team_id: UUID | None = None,
    assignee_id: UUID | None = None,
    unassigned_only: bool = False,
    status: str | None = None,
    priority: str | None = None,
    type: str | None = None,
    search: str | None = None,
    connection: psycopg.Connection | None = None,
) -> dict[str, Any]:
    """Return a page of work items and its total matching count.

    This operation does not apply authorization. Services must ensure
    that filters and returned results are scoped to permitted teams.
    """
    if not 1 <= limit <= 100:
        raise ValueError("Limit must be between 1 and 100.")

    if offset < 0:
        raise ValueError("Offset cannot be negative.")

    if unassigned_only and assignee_id is not None:
        raise ValueError(
            "Specify assignee_id or unassigned_only, not both."
        )

    conditions: list[str] = []
    parameters: list[Any] = []

    if team_id is not None:
        conditions.append("team_id = %s")
        parameters.append(team_id)

    if unassigned_only:
        conditions.append("assignee_id IS NULL")
    elif assignee_id is not None:
        conditions.append("assignee_id = %s")
        parameters.append(assignee_id)

    if status is not None:
        conditions.append("status = %s")
        parameters.append(status)

    if priority is not None:
        conditions.append("priority = %s")
        parameters.append(priority)

    if type is not None:
        conditions.append("type = %s")
        parameters.append(type)

    if search and search.strip():
        conditions.append("(title ILIKE %s OR description ILIKE %s)")
        pattern = f"%{search.strip()}%"
        parameters.extend((pattern, pattern))

    where_clause = (
        f"WHERE {' AND '.join(conditions)}"
        if conditions
        else ""
    )

    count_query = f"""
        SELECT COUNT(*) AS total
        FROM work_items
        {where_clause};
    """

    list_query = f"""
        SELECT
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
            completed_at
        FROM work_items
        {where_clause}
        ORDER BY updated_at DESC, id ASC
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
        log_database_failure(logger, "list_work_items", exc)
        raise WorkItemDatabaseError(
            "Unable to retrieve work items right now."
        ) from None