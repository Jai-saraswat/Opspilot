"""Retrieve a role by UUID."""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

from BACKEND.Postgres.Operations._db import connection_scope, log_database_failure
from BACKEND.Postgres.Operations.authorization.errors import AuthorizationDatabaseError

logger = logging.getLogger(__name__)


def get_role_by_id(
    role_id: UUID,
    *,
    connection: psycopg.Connection | None = None,
) -> dict[str, Any] | None:
    query = """
        SELECT id, name, scope, description, is_system_role, created_at
        FROM roles
        WHERE id = %s;
    """

    try:
        with connection_scope(connection) as conn:
            with conn.cursor(row_factory=dict_row) as cursor:
                cursor.execute(query, (role_id,))
                row = cursor.fetchone()
                return dict(row) if row is not None else None

    except (psycopg.Error, RuntimeError) as exc:
        log_database_failure(logger, "get_role_by_id", exc)
        raise AuthorizationDatabaseError(
            "Unable to retrieve the role right now."
        ) from None