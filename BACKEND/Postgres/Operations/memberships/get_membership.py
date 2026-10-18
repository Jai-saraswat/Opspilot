"""Retrieve a user's membership in a team."""

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
from BACKEND.Postgres.Operations.memberships.errors import MembershipDatabaseError

logger = logging.getLogger(__name__)


def get_membership(
    team_id: UUID,
    user_id: UUID,
    *,
    connection: psycopg.Connection | None = None,
) -> dict[str, Any] | None:
    """Return a membership, or None if it does not exist."""
    query = """
        SELECT id, team_id, user_id, role, joined_at
        FROM team_memberships
        WHERE team_id = %s AND user_id = %s;
    """

    try:
        with connection_scope(connection) as conn:
            with conn.cursor(row_factory=dict_row) as cursor:
                cursor.execute(query, (team_id, user_id))
                row = cursor.fetchone()

                return dict(row) if row is not None else None

    except (psycopg.Error, RuntimeError) as exc:
        log_database_failure(logger, "get_membership", exc)
        raise MembershipDatabaseError(
            "Unable to retrieve the team membership right now."
        ) from None