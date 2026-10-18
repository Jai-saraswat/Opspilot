"""List login sessions for a user."""

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


def list_user_sessions(
    user_id: UUID,
    *,
    limit: int = 50,
    offset: int = 0,
    connection: psycopg.Connection | None = None,
) -> dict[str, Any]:
    """Return a page of sessions and its total matching count."""
    if not 1 <= limit <= 100:
        raise ValueError("Limit must be between 1 and 100.")

    if offset < 0:
        raise ValueError("Offset cannot be negative.")

    count_query = """
        SELECT COUNT(*) AS total
        FROM login_sessions
        WHERE user_id = %s;
    """

    list_query = """
        SELECT id, user_id, expires_at, revoked_at, created_at
        FROM login_sessions
        WHERE user_id = %s
        ORDER BY created_at DESC, id ASC
        LIMIT %s OFFSET %s;
    """

    try:
        with connection_scope(connection) as conn:
            with conn.cursor(row_factory=dict_row) as cursor:
                cursor.execute(count_query, (user_id,))
                total = cursor.fetchone()["total"]

                cursor.execute(
                    list_query,
                    (user_id, limit, offset),
                )
                rows = cursor.fetchall()

                return {
                    "items": [dict(row) for row in rows],
                    "total": total,
                    "limit": limit,
                    "offset": offset,
                }

    except (psycopg.Error, RuntimeError) as exc:
        log_database_failure(logger, "list_user_sessions", exc)
        raise SessionDatabaseError(
            "Unable to retrieve the user's sessions right now."
        ) from None