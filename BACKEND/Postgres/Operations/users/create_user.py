"""Database operation for inserting a user into PostgreSQL.

This module only persists data. Password hashing, input normalization, and
permission checks belong in the service/authentication layers.

Run the application with the project root on PYTHONPATH so imports resolve.
"""

from __future__ import annotations

import logging
from typing import Any

import psycopg
from psycopg import errors as pg_errors
from psycopg.rows import dict_row

from BACKEND.Postgres.Operations._db import (
    connection_scope,
    log_database_failure,
)
from BACKEND.Postgres.Operations.users.errors import (
    InvalidUserRecordError,
    UserAlreadyExistsError,
    UserCreationError,
)

logger = logging.getLogger(__name__)


def create_user(
    *,
    full_name: str,
    email: str,
    password_hash: str,
    connection: psycopg.Connection | None = None,
) -> dict[str, Any]:
    """Insert a user and return only non-sensitive user fields.

    Args:
        full_name: User's full name.
        email: Email address, normalized by the calling service.
        password_hash: Precomputed password hash, never a raw password.
        connection: Optional existing connection owned by the caller.
            Supply this when user creation must participate in a larger
            transaction.

    Returns:
        A dictionary containing the newly created user's public fields.

    Raises:
        UserAlreadyExistsError: Email is already registered.
        InvalidUserRecordError: A database check constraint was violated.
        UserCreationError: The insert or its transaction failed.

    Note:
        If a connection is supplied, the caller owns the transaction.
        Let exceptions propagate out of the transaction context so it can
        roll back all related operations.
    """
    query = """
        INSERT INTO users (
            full_name,
            email,
            password_hash
        )
        VALUES (%s, %s, %s)
        RETURNING
            id,
            full_name,
            email,
            account_status,
            created_at,
            updated_at;
    """

    try:
        with connection_scope(connection) as conn:
            with conn.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    query,
                    (full_name, email, password_hash),
                )
                row = cursor.fetchone()

                if row is None:
                    raise UserCreationError(
                        "The user could not be created. Please try again."
                    )

                # Never return password_hash.
                return dict(row)

    except pg_errors.UniqueViolation as exc:
        constraint_name = exc.diag.constraint_name

        if constraint_name == "uq_users_email_lower":
            raise UserAlreadyExistsError(
                "A user with this email address is already registered."
            ) from None

        log_database_failure(logger, "create_user", exc)
        raise UserCreationError(
            "The user could not be created because of a database constraint."
        ) from None

    except pg_errors.CheckViolation as exc:
        constraint_name = exc.diag.constraint_name

        if constraint_name == "chk_users_full_name":
            raise InvalidUserRecordError(
                "Full name must contain at least one "
                "non-whitespace character."
            ) from None

        log_database_failure(logger, "create_user", exc)
        raise InvalidUserRecordError(
            "One or more user fields are invalid."
        ) from None

    except psycopg.Error as exc:
        log_database_failure(logger, "create_user", exc)
        raise UserCreationError(
            "Unable to create the user right now. Please try again."
        ) from None