"""Retrieve a login session using its refresh-token hash."""

from __future__ import annotations

import logging
from typing import Any

import psycopg
from psycopg.rows import dict_row

from BACKEND.Postgres.Operations._db import (
    connection_scope,
    log_database_failure,
)
from BACKEND.Postgres.Operations.sessions.errors import SessionDatabaseError

logger = logging.getLogger(__name__)


def get_session_by_token_hash(
    refresh_token_hash: str,
    *,
    connection: psycopg.Connection | None = None,
) -> dict[str, Any] | None:
    """Return session metadata, or None if no matching session exists."""
    query = """
        SELECT id, user_id, expires_at, revoked_at, created_at
        FROM login_sessions
        WHERE refresh_token_hash = %s;
    """

    try:
        with connection_scope(connection) as conn:
            with conn.cursor(row_factory=dict_row) as cursor:
                cursor.execute(query, (refresh_token_hash,))
                row = cursor.fetchone()

                return dict(row) if row is not None else None

    except (psycopg.Error, RuntimeError) as exc:
        log_database_failure(
            logger,
            "get_session_by_token_hash",
            exc,
        )
        raise SessionDatabaseError(
            "Unable to retrieve the login session right now."
        ) from None