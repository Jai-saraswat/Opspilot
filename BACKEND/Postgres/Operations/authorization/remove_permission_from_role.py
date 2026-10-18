"""Remove a permission from a role."""

from __future__ import annotations

import logging
from uuid import UUID

import psycopg

from BACKEND.Postgres.Operations._db import connection_scope, log_database_failure
from BACKEND.Postgres.Operations.authorization.errors import AuthorizationDatabaseError

logger = logging.getLogger(__name__)


def remove_permission_from_role(
    role_id: UUID,
    permission_id: UUID,
    *,
    connection: psycopg.Connection | None = None,
) -> bool:
    query = """
        DELETE FROM role_permissions
        WHERE role_id = %s AND permission_id = %s
        RETURNING role_id;
    """

    try:
        with connection_scope(connection) as conn:
            with conn.cursor() as cursor:
                cursor.execute(query, (role_id, permission_id))
                return cursor.fetchone() is not None

    except (psycopg.Error, RuntimeError) as exc:
        log_database_failure(logger, "remove_permission_from_role", exc)
        raise AuthorizationDatabaseError(
            "Unable to remove the permission from the role."
        ) from None