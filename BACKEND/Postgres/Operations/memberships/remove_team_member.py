"""Remove a user from a team."""

from __future__ import annotations

import logging
from uuid import UUID

import psycopg

from BACKEND.Postgres.Operations._db import (
    connection_scope,
    log_database_failure,
)
from BACKEND.Postgres.Operations.memberships.errors import MembershipDatabaseError

logger = logging.getLogger(__name__)


def remove_team_member(
    team_id: UUID,
    user_id: UUID,
    *,
    connection: psycopg.Connection | None = None,
) -> bool:
    """Remove a membership; return whether a record was deleted."""
    query = """
        DELETE FROM team_memberships
        WHERE team_id = %s AND user_id = %s
        RETURNING id;
    """

    try:
        with connection_scope(connection) as conn:
            with conn.cursor() as cursor:
                cursor.execute(query, (team_id, user_id))
                return cursor.fetchone() is not None

    except (psycopg.Error, RuntimeError) as exc:
        log_database_failure(logger, "remove_team_member", exc)
        raise MembershipDatabaseError(
            "Unable to remove the team member right now."
        ) from None