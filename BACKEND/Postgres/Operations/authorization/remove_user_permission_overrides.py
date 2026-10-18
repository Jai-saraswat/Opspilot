"""Remove a user's permission override from PostgreSQL."""

from __future__ import annotations

import logging
from uuid import UUID

import psycopg

from BACKEND.Postgres.Operations._db import (
    connection_scope,
    log_database_failure,
)
from BACKEND.Postgres.Operations.authorization.errors import (
    AuthorizationDatabaseError,
)

logger = logging.getLogger(__name__)


def remove_user_permission_overrides(
    *,
    user_id: UUID,
    permission_id: UUID,
    team_id: UUID | None = None,
    connection: psycopg.Connection | None = None,
) -> bool:
    """Remove a permission override for a user.

    Args:
        user_id: User whose override should be removed.
        permission_id: Permission associated with the override.
        team_id: Team scope of the override. None targets the global
            override only.
        connection: Optional caller-owned PostgreSQL connection.

    Returns:
        True if an override was deleted; otherwise False.

    Notes:
        - A global override and a team-scoped override are treated as
          separate records.
        - When a connection is supplied, the caller owns the transaction.
        - Repeating the operation is safe; a missing override returns False.
    """
    query = """
        DELETE FROM user_permission_overrides
        WHERE user_id = %s
          AND permission_id = %s
          AND team_id IS NOT DISTINCT FROM %s
        RETURNING id;
    """

    try:
        with connection_scope(connection) as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    query,
                    (user_id, permission_id, team_id),
                )
                deleted_row = cursor.fetchone()

                return deleted_row is not None

    except (psycopg.Error, RuntimeError) as exc:
        log_database_failure(
            logger,
            "remove_user_permission_overrides",
            exc,
        )
        raise AuthorizationDatabaseError(
            "Unable to remove the user permission override."
        ) from None