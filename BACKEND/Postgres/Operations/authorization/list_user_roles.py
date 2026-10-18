"""List the roles assigned to a user."""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

from BACKEND.Postgres.Operations._db import connection_scope, log_database_failure
from BACKEND.Postgres.Operations.authorization.errors import AuthorizationDatabaseError

logger = logging.getLogger(__name__)


def list_user_roles(
    user_id: UUID,
    *,
    scope: str | None = None,
    connection: psycopg.Connection | None = None,
) -> list[dict[str, Any]]:
    conditions = ["ur.user_id = %s"]
    parameters: list[Any] = [user_id]

    if scope is not None:
        conditions.append("r.scope = %s")
        parameters.append(scope)

    query = f"""
        SELECT
            r.id,
            r.name,
            r.scope,
            r.description,
            r.is_system_role,
            ur.assigned_by,
            ur.assigned_at
        FROM user_roles AS ur
        JOIN roles AS r ON r.id = ur.role_id
        WHERE {" AND ".join(conditions)}
        ORDER BY r.scope, r.name;
    """

    try:
        with connection_scope(connection) as conn:
            with conn.cursor(row_factory=dict_row) as cursor:
                cursor.execute(query, tuple(parameters))
                return [dict(row) for row in cursor.fetchall()]

    except (psycopg.Error, RuntimeError) as exc:
        log_database_failure(logger, "list_user_roles", exc)
        raise AuthorizationDatabaseError(
            "Unable to retrieve the user's roles."
        ) from None