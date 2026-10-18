"""Retrieve a permission using its unique key."""

from __future__ import annotations

import logging
from typing import Any

import psycopg
from psycopg.rows import dict_row

from BACKEND.Postgres.Operations._db import connection_scope, log_database_failure
from BACKEND.Postgres.Operations.authorization.errors import AuthorizationDatabaseError

logger = logging.getLogger(__name__)


def get_permission_by_key(
    permission_key: str,
    *,
    connection: psycopg.Connection | None = None,
) -> dict[str, Any] | None:
    query = """
        SELECT id, permission_key, description
        FROM permissions
        WHERE permission_key = %s;
    """

    try:
        with connection_scope(connection) as conn:
            with conn.cursor(row_factory=dict_row) as cursor:
                cursor.execute(query, (permission_key,))
                row = cursor.fetchone()
                return dict(row) if row is not None else None

    except (psycopg.Error, RuntimeError) as exc:
        log_database_failure(logger, "get_permission_by_key", exc)
        raise AuthorizationDatabaseError(
            "Unable to retrieve the permission right now."
        ) from None