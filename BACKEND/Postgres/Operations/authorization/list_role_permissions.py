"""List permissions assigned to a role."""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

from BACKEND.Postgres.Operations._db import connection_scope, log_database_failure
from BACKEND.Postgres.Operations.authorization.errors import AuthorizationDatabaseError

logger = logging.getLogger(__name__)


def list_role_permissions(
    role_id: UUID,
    *,
    connection: psycopg.Connection | None = None,
) -> list[dict[str, Any]]:
    query = """
        SELECT p.id, p.permission_key, p.description
        FROM role_permissions AS rp
        JOIN permissions AS p ON p.id = rp.permission_id
        WHERE rp.role_id = %s
        ORDER BY p.permission_key;
    """

    try:
        with connection_scope(connection) as conn:
            with conn.cursor(row_factory=dict_row) as cursor:
                cursor.execute(query, (role_id,))
                return [dict(row) for row in cursor.fetchall()]

    except (psycopg.Error, RuntimeError) as exc:
        log_database_failure(logger, "list_role_permissions", exc)
        raise AuthorizationDatabaseError(
            "Unable to retrieve the role's permissions."
        ) from None