"""Retrieve permission overrides for a user."""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

from BACKEND.Postgres.Operations._db import connection_scope, log_database_failure
from BACKEND.Postgres.Operations.authorization.errors import AuthorizationDatabaseError

logger = logging.getLogger(__name__)


def get_user_permission_overrides(
    user_id: UUID,
    *,
    team_id: UUID | None = None,
    connection: psycopg.Connection | None = None,
) -> list[dict[str, Any]]:
    if team_id is None:
        query = """
            SELECT
                id, user_id, permission_id, team_id,
                effect, assigned_by, created_at
            FROM user_permission_overrides
            WHERE user_id = %s
            ORDER BY permission_id, team_id NULLS FIRST;
        """
        parameters = (user_id,)
    else:
        query = """
            SELECT
                id, user_id, permission_id, team_id,
                effect, assigned_by, created_at
            FROM user_permission_overrides
            WHERE user_id = %s
              AND (team_id IS NULL OR team_id = %s)
            ORDER BY permission_id, team_id NULLS FIRST;
        """
        parameters = (user_id, team_id)

    try:
        with connection_scope(connection) as conn:
            with conn.cursor(row_factory=dict_row) as cursor:
                cursor.execute(query, parameters)
                return [dict(row) for row in cursor.fetchall()]

    except (psycopg.Error, RuntimeError) as exc:
        log_database_failure(
            logger,
            "get_user_permission_overrides",
            exc,
        )
        raise AuthorizationDatabaseError(
            "Unable to retrieve permission overrides."
        ) from None