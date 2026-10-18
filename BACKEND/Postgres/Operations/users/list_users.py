"""List users with pagination and optional filtering."""

import logging
from typing import Any

import psycopg
from psycopg.rows import dict_row

from BACKEND.Postgres.Operations._db import (
    connection_scope,
    log_database_failure,
)
from BACKEND.Postgres.Operations.users.errors import UserDatabaseError

logger = logging.getLogger(__name__)


def list_users(
    *,
    limit: int = 50,
    offset: int = 0,
    account_status: str | None = None,
    search: str | None = None,
    connection: psycopg.Connection | None = None,
) -> dict[str, Any]:
    """Return a page of users without exposing password hashes.

    Invalid pagination values raise ValueError. Filter values are passed
    as SQL parameters rather than inserted into the SQL string.
    """
    if not 1 <= limit <= 100:
        raise ValueError("Limit must be between 1 and 100.")

    if offset < 0:
        raise ValueError("Offset cannot be negative.")

    conditions: list[str] = []
    parameters: list[Any] = []

    if account_status is not None:
        conditions.append("account_status = %s")
        parameters.append(account_status)

    if search:
        conditions.append(
            "(full_name ILIKE %s OR email ILIKE %s)"
        )
        pattern = f"%{search}%"
        parameters.extend((pattern, pattern))

    where_clause = (
        f"WHERE {' AND '.join(conditions)}"
        if conditions
        else ""
    )

    count_query = f"""
        SELECT COUNT(*) AS total
        FROM users
        {where_clause};
    """

    list_query = f"""
        SELECT
            id,
            full_name,
            email,
            account_status,
            created_at,
            updated_at
        FROM users
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
        log_database_failure(logger, "list_users", exc)
        raise UserDatabaseError(
            "Unable to retrieve users right now."
        ) from None