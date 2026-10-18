"""List teams that a user belongs to."""

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
from BACKEND.Postgres.Operations.memberships.errors import MembershipDatabaseError

logger = logging.getLogger(__name__)


def list_user_teams(
    user_id: UUID,
    *,
    limit: int = 50,
    offset: int = 0,
    search: str | None = None,
    connection: psycopg.Connection | None = None,
) -> dict[str, Any]:
    """Return a page of teams associated with a user."""
    if not 1 <= limit <= 100:
        raise ValueError("Limit must be between 1 and 100.")

    if offset < 0:
        raise ValueError("Offset cannot be negative.")

    conditions = ["tm.user_id = %s"]
    parameters: list[Any] = [user_id]

    if search and search.strip():
        conditions.append(
            "(t.name ILIKE %s OR t.description ILIKE %s)"
        )
        pattern = f"%{search.strip()}%"
        parameters.extend((pattern, pattern))

    where_clause = "WHERE " + " AND ".join(conditions)

    count_query = f"""
        SELECT COUNT(*) AS total
        FROM team_memberships AS tm
        JOIN teams AS t ON t.id = tm.team_id
        {where_clause};
    """

    list_query = f"""
        SELECT
            t.id,
            t.name,
            t.description,
            t.created_by,
            t.created_at,
            t.updated_at,
            tm.role AS membership_role,
            tm.joined_at AS membership_joined_at
        FROM team_memberships AS tm
        JOIN teams AS t ON t.id = tm.team_id
        {where_clause}
        ORDER BY tm.joined_at ASC, t.id ASC
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
        log_database_failure(logger, "list_user_teams", exc)
        raise MembershipDatabaseError(
            "Unable to retrieve the user's teams right now."
        ) from None