"""List roles with pagination and optional scope filtering."""

from __future__ import annotations

import logging
from typing import Any

import psycopg
from psycopg.rows import dict_row

from BACKEND.Postgres.Operations._db import connection_scope, log_database_failure
from BACKEND.Postgres.Operations.authorization.errors import AuthorizationDatabaseError

logger = logging.getLogger(__name__)


def list_roles(
    *,
    limit: int = 50,
    offset: int = 0,
    scope: str | None = None,
    connection: psycopg.Connection | None = None,
) -> dict[str, Any]:
    if not 1 <= limit <= 100:
        raise ValueError("Limit must be between 1 and 100.")
    if offset < 0:
        raise ValueError("Offset cannot be negative.")

    where_clause = "WHERE scope = %s" if scope is not None else ""
    parameters: tuple[Any, ...] = (scope,) if scope is not None else ()

    count_query = f"SELECT COUNT(*) AS total FROM roles {where_clause};"
    list_query = f"""
        SELECT id, name, scope, description, is_system_role, created_at
        FROM roles
        {where_clause}
        ORDER BY scope, name, id
        LIMIT %s OFFSET %s;
    """

    try:
        with connection_scope(connection) as conn:
            with conn.cursor(row_factory=dict_row) as cursor:
                cursor.execute(count_query, parameters)
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
        log_database_failure(logger, "list_roles", exc)
        raise AuthorizationDatabaseError(
            "Unable to retrieve roles right now."
        ) from None