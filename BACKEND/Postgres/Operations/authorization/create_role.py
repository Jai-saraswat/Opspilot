"""Insert a role definition."""

from __future__ import annotations

import logging
from typing import Any

import psycopg
from psycopg import errors as pg_errors
from psycopg.rows import dict_row

from BACKEND.Postgres.Operations._db import connection_scope, log_database_failure
from BACKEND.Postgres.Operations.authorization.errors import (
    AuthorizationDatabaseError,
    InvalidAuthorizationRecordError,
    RoleAlreadyExistsError,
)

logger = logging.getLogger(__name__)


def create_role(
    *,
    name: str,
    scope: str,
    description: str | None = None,
    is_system_role: bool = False,
    connection: psycopg.Connection | None = None,
) -> dict[str, Any]:
    query = """
        INSERT INTO roles (name, scope, description, is_system_role)
        VALUES (%s, %s, %s, %s)
        RETURNING id, name, scope, description, is_system_role, created_at;
    """

    try:
        with connection_scope(connection) as conn:
            with conn.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    query,
                    (name, scope, description, is_system_role),
                )
                row = cursor.fetchone()

                if row is None:
                    raise AuthorizationDatabaseError(
                        "The role could not be created."
                    )

                return dict(row)

    except pg_errors.UniqueViolation as exc:
        if exc.diag.constraint_name == "uq_roles_scope_name":
            raise RoleAlreadyExistsError(
                "A role with this name and scope already exists."
            ) from None

        log_database_failure(logger, "create_role", exc)
        raise AuthorizationDatabaseError(
            "Unable to create the role."
        ) from None

    except pg_errors.CheckViolation as exc:
        log_database_failure(logger, "create_role", exc)
        raise InvalidAuthorizationRecordError(
            "The role scope is invalid."
        ) from None

    except (psycopg.Error, RuntimeError) as exc:
        log_database_failure(logger, "create_role", exc)
        raise AuthorizationDatabaseError(
            "Unable to create the role right now."
        ) from None