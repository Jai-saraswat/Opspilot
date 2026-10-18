"""Retrieve a public user record by email."""

import logging
from typing import Any

import psycopg
from psycopg.rows import dict_row

from BACKEND.Postgres.Operations._db import (
    connection_scope,
    log_database_failure,
)
from BACKEND.Postgres.Operations.users.errors import UserDatabaseError

logger = logging.getLogger(__name__)


def get_user_by_email(
    email: str,
    *,
    connection: psycopg.Connection | None = None,
) -> dict[str, Any] | None:
    """Return a public user record, or None when no match exists."""
    query = """
        SELECT
            id,
            full_name,
            email,
            account_status,
            created_at,
            updated_at
        FROM users
        WHERE LOWER(email) = LOWER(%s);
    """

    try:
        with connection_scope(connection) as conn:
            with conn.cursor(row_factory=dict_row) as cursor:
                cursor.execute(query, (email,))
                row = cursor.fetchone()

                return dict(row) if row is not None else None

    except (psycopg.Error, RuntimeError) as exc:
        log_database_failure(logger, "get_user_by_email", exc)
        raise UserDatabaseError(
            "Unable to retrieve the user right now."
        ) from None