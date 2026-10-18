"""Delete expired login sessions in bounded batches."""

from __future__ import annotations

import logging

import psycopg

from BACKEND.Postgres.Operations._db import (
    connection_scope,
    log_database_failure,
)
from BACKEND.Postgres.Operations.sessions.errors import SessionDatabaseError

logger = logging.getLogger(__name__)


def delete_expired_sessions(
    *,
    batch_size: int = 500,
    connection: psycopg.Connection | None = None,
) -> int:
    """Delete at most batch_size expired sessions and return the count."""
    if not 1 <= batch_size <= 5000:
        raise ValueError("Batch size must be between 1 and 5000.")

    query = """
        WITH expired AS (
            SELECT id
            FROM login_sessions
            WHERE expires_at <= CURRENT_TIMESTAMP
            ORDER BY expires_at ASC
            LIMIT %s
            FOR UPDATE SKIP LOCKED
        )
        DELETE FROM login_sessions AS sessions
        USING expired
        WHERE sessions.id = expired.id
        RETURNING sessions.id;
    """

    try:
        with connection_scope(connection) as conn:
            with conn.cursor() as cursor:
                cursor.execute(query, (batch_size,))
                return len(cursor.fetchall())

    except (psycopg.Error, RuntimeError) as exc:
        log_database_failure(logger, "delete_expired_sessions", exc)
        raise SessionDatabaseError(
            "Unable to clean up expired sessions right now."
        ) from None