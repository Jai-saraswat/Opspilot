"""Revoke all unrevoked login sessions for a user."""

from __future__ import annotations

import logging
from uuid import UUID

import psycopg

from BACKEND.Postgres.Operations._db import (
    connection_scope,
    log_database_failure,
)
from BACKEND.Postgres.Operations.sessions.errors import SessionDatabaseError

logger = logging.getLogger(__name__)


def revoke_user_sessions(
    user_id: UUID,
    *,
    connection: psycopg.Connection | None = None,
) -> int:
    """Revoke all unrevoked sessions and return the number changed."""
    query = """
        UPDATE login_sessions
        SET revoked_at = CURRENT_TIMESTAMP
        WHERE user_id = %s
          AND revoked_at IS NULL
        RETURNING id;
    """

    try:
        with connection_scope(connection) as conn:
            with conn.cursor() as cursor:
                cursor.execute(query, (user_id,))
                return len(cursor.fetchall())

    except (psycopg.Error, RuntimeError) as exc:
        log_database_failure(logger, "revoke_user_sessions", exc)
        raise SessionDatabaseError(
            "Unable to revoke the user's sessions right now."
        ) from None