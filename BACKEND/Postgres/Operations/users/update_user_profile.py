"""Update selected user profile fields."""

import logging
from typing import Any
from uuid import UUID

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
    UserDatabaseError,
)

logger = logging.getLogger(__name__)


def update_user_profile(
    user_id: UUID,
    *,
    full_name: str | None = None,
    email: str | None = None,
    connection: psycopg.Connection | None = None,
) -> dict[str, Any] | None:
    """Update only supplied profile fields.

    Returns the updated public record, or None if the user does not exist.
    None means 'leave unchanged'; this function does not set NOT NULL
    database fields to NULL.
    """
    updates: list[str] = []
    parameters: list[Any] = []

    if full_name is not None:
        updates.append("full_name = %s")
        parameters.append(full_name)

    if email is not None:
        updates.append("email = %s")
        parameters.append(email)

    if not updates:
        raise InvalidUserRecordError(
            "Provide at least one profile field to update."
        )

    updates.append("updated_at = CURRENT_TIMESTAMP")
    parameters.append(user_id)

    query = f"""
        UPDATE users
        SET {", ".join(updates)}
        WHERE id = %s
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
                cursor.execute(query, tuple(parameters))
                row = cursor.fetchone()

                return dict(row) if row is not None else None

    except pg_errors.UniqueViolation as exc:
        if exc.diag.constraint_name == "uq_users_email_lower":
            raise UserAlreadyExistsError(
                "A user with this email address is already registered."
            ) from None

        log_database_failure(logger, "update_user_profile", exc)
        raise UserDatabaseError(
            "Unable to update the user profile right now."
        ) from None

    except pg_errors.CheckViolation:
        raise InvalidUserRecordError(
            "One or more profile fields are invalid."
        ) from None

    except (psycopg.Error, RuntimeError) as exc:
        log_database_failure(logger, "update_user_profile", exc)
        raise UserDatabaseError(
            "Unable to update the user profile right now."
        ) from None