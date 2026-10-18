"""List the registered permission definitions."""

from __future__ import annotations

import logging
from typing import Any

import psycopg
from psycopg.rows import dict_row

from BACKEND.Postgres.Operations._db import connection_scope, log_database_failure
from BACKEND.Postgres.Operations.authorization.errors import AuthorizationDatabaseError

logger = logging.getLogger(__name__)


def list_permissions(
    *,
    connection: psycopg.Connection | None = None,
) -> list[dict[str, Any]]:
    query = """
        SELECT id, permission_key, description
        FROM permissions
        ORDER BY permission_key;
    """

    try:
        with connection_scope(connection) as conn:
            with conn.cursor(row_factory=dict_row) as cursor:
                cursor.execute(query)
                return [dict(row) for row in cursor.fetchall()]

    except (psycopg.Error, RuntimeError) as exc:
        log_database_failure(logger, "list_permissions", exc)
        raise AuthorizationDatabaseError(
            "Unable to retrieve permissions right now."
        ) from None