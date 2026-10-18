"""Retrieve a role by name and scope."""

from __future__ import annotations

import logging
from typing import Any

import psycopg
from psycopg.rows import dict_row

from BACKEND.Postgres.Operations._db import connection_scope, log_database_failure
from BACKEND.Postgres.Operations.authorization.errors import AuthorizationDatabaseError

logger = logging.getLogger(__name__)


def get_role_by_name(
    name: str,
    scope: str,
    *,
    connection: psycopg.Connection | None = None,
) -> dict[str, Any] | None:
    query = """
        SELECT id, name, scope, description, is_system_role, created_at
        FROM roles
        WHERE name = %s AND scope = %s;
    """

    try:
        with connection_scope(connection) as conn:
            with conn.cursor(row_factory=dict_row) as cursor:
                cursor.execute(query, (name, scope))
                row = cursor.fetchone()
                return dict(row) if row is not None else None

    except (psycopg.Error, RuntimeError) as exc:
        log_database_failure(logger, "get_role_by_name", exc)
        raise AuthorizationDatabaseError(
            "Unable to retrieve the role right now."
        ) from None