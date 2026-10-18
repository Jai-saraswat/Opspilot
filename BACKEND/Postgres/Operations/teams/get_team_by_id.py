"""Retrieve a team by UUID."""

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
from BACKEND.Postgres.Operations.teams.errors import TeamDatabaseError

logger = logging.getLogger(__name__)


def get_team_by_id(
    team_id: UUID,
    *,
    connection: psycopg.Connection | None = None,
) -> dict[str, Any] | None:
    """Return the team record, or None if it doesn't exist."""
    query = """
        SELECT
            id,
            name,
            description,
            created_by,
            created_at,
            updated_at
        FROM teams
        WHERE id = %s;
    """

    try:
        with connection_scope(connection) as conn:
            with conn.cursor(row_factory=dict_row) as cursor:
                cursor.execute(query, (team_id,))
                row = cursor.fetchone()

                return dict(row) if row is not None else None

    except (psycopg.Error, RuntimeError) as exc:
        log_database_failure(logger, "get_team_by_id", exc)
        raise TeamDatabaseError(
            "Unable to retrieve the team right now."
        ) from None