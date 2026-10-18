"""Update a user's account status."""

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
    UserDatabaseError,
)

logger = logging.getLogger(__name__)


def update_user_status(
    user_id: UUID,
    account_status: str,
    *,
    connection: psycopg.Connection | None = None,
) -> dict[str, Any] | None:
    """Update account status and return the public user record.

    Returns None if the user does not exist.
    """
    query = """
        UPDATE users
        SET
            account_status = %s,
            updated_at = CURRENT_TIMESTAMP
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
                cursor.execute(query, (account_status, user_id))
                row = cursor.fetchone()

                return dict(row) if row is not None else None

    except pg_errors.CheckViolation:
        raise InvalidUserRecordError(
            "The supplied account status is invalid."
        ) from None

    except (psycopg.Error, RuntimeError) as exc:
        log_database_failure(logger, "update_user_status", exc)
        raise UserDatabaseError(
            "Unable to update the account status right now."
        ) from None