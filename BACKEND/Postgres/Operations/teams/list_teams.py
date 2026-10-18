"""List teams with pagination and optional name search."""

from __future__ import annotations

import logging
from typing import Any

import psycopg
from psycopg.rows import dict_row

from BACKEND.Postgres.Operations._db import (
    connection_scope,
    log_database_failure,
)
from BACKEND.Postgres.Operations.teams.errors import TeamDatabaseError

logger = logging.getLogger(__name__)


def list_teams(
    *,
    limit: int = 50,
    offset: int = 0,
    search: str | None = None,
    connection: psycopg.Connection | None = None,
) -> dict[str, Any]:
    """Return a paginated list of teams.

    Raises:
        ValueError: If pagination parameters are invalid.
        TeamDatabaseError: If PostgreSQL fails.
    """
    if not 1 <= limit <= 100:
        raise ValueError("Limit must be between 1 and 100.")

    if offset < 0:
        raise ValueError("Offset cannot be negative.")

    conditions: list[str] = []
    parameters: list[Any] = []

    if search is not None and search.strip():
        conditions.append(
            "(name ILIKE %s OR description ILIKE %s)"
        )
        pattern = f"%{search.strip()}%"
        parameters.extend((pattern, pattern))

    where_clause = (
        f"WHERE {' AND '.join(conditions)}"
        if conditions
        else ""
    )

    count_query = f"""
        SELECT COUNT(*) AS total
        FROM teams
        {where_clause};
    """

    list_query = f"""
        SELECT
            id,
            name,
            description,
            created_by,
            created_at,
            updated_at
        FROM teams
        {where_clause}
        ORDER BY created_at DESC, id ASC
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
        log_database_failure(logger, "list_teams", exc)
        raise TeamDatabaseError(
            "Unable to retrieve teams right now."
        ) from None