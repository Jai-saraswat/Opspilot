"""Grant a permission to a role."""

from __future__ import annotations

import logging
from uuid import UUID

import psycopg
from psycopg import errors as pg_errors

from BACKEND.Postgres.Operations._db import connection_scope, log_database_failure
from BACKEND.Postgres.Operations.authorization.errors import (
    AuthorizationDatabaseError,
    AuthorizationRelatedRecordNotFoundError,
)

logger = logging.getLogger(__name__)


def add_permission_to_role(
    role_id: UUID,
    permission_id: UUID,
    *,
    connection: psycopg.Connection | None = None,
) -> bool:
    query = """
        INSERT INTO role_permissions (role_id, permission_id)
        VALUES (%s, %s)
        ON CONFLICT (role_id, permission_id) DO NOTHING
        RETURNING role_id;
    """

    try:
        with connection_scope(connection) as conn:
            with conn.cursor() as cursor:
                cursor.execute(query, (role_id, permission_id))
                return cursor.fetchone() is not None

    except pg_errors.ForeignKeyViolation:
        raise AuthorizationRelatedRecordNotFoundError(
            "The specified role or permission does not exist."
        ) from None

    except (psycopg.Error, RuntimeError) as exc:
        log_database_failure(logger, "add_permission_to_role", exc)
        raise AuthorizationDatabaseError(
            "Unable to add the permission to the role."
        ) from None