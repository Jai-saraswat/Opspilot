"""Remove a role assignment from a user."""

from __future__ import annotations

import logging
from uuid import UUID

import psycopg

from BACKEND.Postgres.Operations._db import connection_scope, log_database_failure
from BACKEND.Postgres.Operations.authorization.errors import AuthorizationDatabaseError

logger = logging.getLogger(__name__)


def remove_role_from_user(
    user_id: UUID,
    role_id: UUID,
    *,
    connection: psycopg.Connection | None = None,
) -> bool:
    query = """
        DELETE FROM user_roles
        WHERE user_id = %s AND role_id = %s
        RETURNING user_id;
    """

    try:
        with connection_scope(connection) as conn:
            with conn.cursor() as cursor:
                cursor.execute(query, (user_id, role_id))
                return cursor.fetchone() is not None

    except (psycopg.Error, RuntimeError) as exc:
        log_database_failure(logger, "remove_role_from_user", exc)
        raise AuthorizationDatabaseError(
            "Unable to remove the role assignment."
        ) from None