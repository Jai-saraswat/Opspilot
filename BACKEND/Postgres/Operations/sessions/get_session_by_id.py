"""Retrieve a login session by its UUID."""

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


def get_session_by_id(
    session_id: UUID,
    *,
    connection: psycopg.Connection | None = None,
) -> dict[str, Any] | None:
    """Return session metadata, or None if the session does not exist."""
    query = """
        SELECT id, user_id, expires_at, revoked_at, created_at
        FROM login_sessions
        WHERE id = %s;
    """

    try:
        with connection_scope(connection) as conn:
            with conn.cursor(row_factory=dict_row) as cursor:
                cursor.execute(query, (session_id,))
                row = cursor.fetchone()

                return dict(row) if row is not None else None

    except (psycopg.Error, RuntimeError) as exc:
        log_database_failure(logger, "get_session_by_id", exc)
        raise SessionDatabaseError(
            "Unable to retrieve the login session right now."
        ) from None