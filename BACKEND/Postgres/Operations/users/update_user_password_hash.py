"""Update a user's stored password hash."""

import logging
from typing import Any
from uuid import UUID

import psycopg
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


def update_user_password_hash(
    user_id: UUID,
    password_hash: str,
    *,
    connection: psycopg.Connection | None = None,
) -> dict[str, Any] | None:
    """Persist a precomputed password hash.

    Returns the public user record, never the password hash itself.
    Returns None if the user does not exist.
    """
    if not password_hash or not password_hash.strip():
        raise InvalidUserRecordError(
            "A valid password hash must be supplied."
        )

    query = """
        UPDATE users
        SET
            password_hash = %s,
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
                cursor.execute(query, (password_hash, user_id))
                row = cursor.fetchone()

                return dict(row) if row is not None else None

    except (psycopg.Error, RuntimeError) as exc:
        # Do not log the hash or SQL parameters.
        log_database_failure(
            logger,
            "update_user_password_hash",
            exc,
        )
        raise UserDatabaseError(
            "Unable to update the password right now."
        ) from None