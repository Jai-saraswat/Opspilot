"""List members of a team with pagination and optional filters."""

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


def list_team_members(
    team_id: UUID,
    *,
    limit: int = 50,
    offset: int = 0,
    role: str | None = None,
    search: str | None = None,
    connection: psycopg.Connection | None = None,
) -> dict[str, Any]:
    """Return a page of team members and pagination metadata."""
    if not 1 <= limit <= 100:
        raise ValueError("Limit must be between 1 and 100.")

    if offset < 0:
        raise ValueError("Offset cannot be negative.")

    conditions = ["tm.team_id = %s"]
    parameters: list[Any] = [team_id]

    if role is not None:
        conditions.append("tm.role = %s")
        parameters.append(role)

    if search and search.strip():
        conditions.append(
            "(u.full_name ILIKE %s OR u.email ILIKE %s)"
        )
        pattern = f"%{search.strip()}%"
        parameters.extend((pattern, pattern))

    where_clause = "WHERE " + " AND ".join(conditions)

    count_query = f"""
        SELECT COUNT(*) AS total
        FROM team_memberships AS tm
        JOIN users AS u ON u.id = tm.user_id
        {where_clause};
    """

    list_query = f"""
        SELECT
            tm.id AS membership_id,
            tm.team_id,
            tm.user_id,
            tm.role,
            tm.joined_at,
            u.full_name,
            u.email,
            u.account_status
        FROM team_memberships AS tm
        JOIN users AS u ON u.id = tm.user_id
        {where_clause}
        ORDER BY tm.joined_at ASC, tm.id ASC
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
        log_database_failure(logger, "list_team_members", exc)
        raise MembershipDatabaseError(
            "Unable to retrieve team members right now."
        ) from None