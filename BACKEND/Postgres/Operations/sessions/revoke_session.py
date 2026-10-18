"""Revoke an individual login session."""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

from BACKEND.Postgres.Operations._db import (
    connection_scope,
    log_database_failure,
)
from BACKEND.Postgres.Operations.sessions.errors import SessionDatabaseError

logger = logging.getLogger(__name__)


def revoke_session(
    session_id: UUID,
    *,
    connection: psycopg.Connection | None = None,
) -> dict[str, Any] | None:
    """Revoke a session or return None if it does not exist."""
    query = """
        UPDATE login_sessions
        SET revoked_at = COALESCE(revoked_at, CURRENT_TIMESTAMP)
        WHERE id = %s
        RETURNING id, user_id, expires_at, revoked_at, created_at;
    """

    try:
        with connection_scope(connection) as conn:
            with conn.cursor(row_factory=dict_row) as cursor:
                cursor.execute(query, (session_id,))
                row = cursor.fetchone()

                return dict(row) if row is not None else None

    except (psycopg.Error, RuntimeError) as exc:
        log_database_failure(logger, "revoke_session", exc)
        raise SessionDatabaseError(
            "Unable to revoke the login session right now."
        ) from None