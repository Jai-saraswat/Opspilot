"""Assign a role to a user."""

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


def assign_role_to_user(
    *,
    user_id: UUID,
    role_id: UUID,
    assigned_by: UUID | None = None,
    connection: psycopg.Connection | None = None,
) -> bool:
    query = """
        INSERT INTO user_roles (user_id, role_id, assigned_by)
        VALUES (%s, %s, %s)
        ON CONFLICT (user_id, role_id) DO NOTHING
        RETURNING user_id;
    """

    try:
        with connection_scope(connection) as conn:
            with conn.cursor() as cursor:
                cursor.execute(query, (user_id, role_id, assigned_by))
                return cursor.fetchone() is not None

    except pg_errors.ForeignKeyViolation as exc:
        constraint = exc.diag.constraint_name

        if constraint in {
            "user_roles_user_id_fkey",
            "user_roles_role_id_fkey",
            "user_roles_assigned_by_fkey",
        }:
            raise AuthorizationRelatedRecordNotFoundError(
                "A referenced user or role does not exist."
            ) from None

        log_database_failure(logger, "assign_role_to_user", exc)
        raise AuthorizationDatabaseError(
            "Unable to assign the role."
        ) from None

    except (psycopg.Error, RuntimeError) as exc:
        log_database_failure(logger, "assign_role_to_user", exc)
        raise AuthorizationDatabaseError(
            "Unable to assign the role right now."
        ) from None