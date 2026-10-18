"""Delete a team by UUID."""

from __future__ import annotations

import logging
from uuid import UUID

import psycopg
from psycopg import errors as pg_errors

from BACKEND.Postgres.Operations._db import (
    connection_scope,
    log_database_failure,
)
from BACKEND.Postgres.Operations.teams.errors import (
    TeamDatabaseError,
    TeamInUseError,
)

logger = logging.getLogger(__name__)


def delete_team(
    team_id: UUID,
    *,
    connection: psycopg.Connection | None = None,
) -> bool:
    """Delete a team by UUID.

    Returns:
        True: The team was deleted.
        False: No team with the supplied UUID exists.

    Raises:
        TeamInUseError: The team cannot be deleted because related
            records restrict its deletion.
        TeamDatabaseError: Another database error occurred.

    Transaction ownership:
        If connection is supplied, the caller owns the transaction.
        Otherwise, connection_scope manages the database connection
        and transaction.
    """
    query = """
        DELETE FROM teams
        WHERE id = %s
        RETURNING id;
    """

    try:
        with connection_scope(connection) as conn:
            with conn.cursor() as cursor:
                cursor.execute(query, (team_id,))
                return cursor.fetchone() is not None

    except pg_errors.RestrictViolation as exc:
        # PostgreSQL SQLSTATE 23001:
        # deletion is restricted by a dependent record.
        log_database_failure(
            logger,
            "delete_team",
            exc,
        )
        raise TeamInUseError(
            "The team cannot be deleted because it is still "
            "referenced by existing records."
        ) from None

    except pg_errors.ForeignKeyViolation as exc:
        # PostgreSQL SQLSTATE 23503.
        # Keep the specific work-item restriction understandable
        # and translate unexpected FK failures safely as well.
        if exc.diag.constraint_name == "work_items_team_id_fkey":
            raise TeamInUseError(
                "This team cannot be deleted while work items "
                "reference it."
            ) from None

        log_database_failure(
            logger,
            "delete_team",
            exc,
        )
        raise TeamDatabaseError(
            "Unable to delete the team because related records "
            "still exist."
        ) from None

    except (psycopg.Error, RuntimeError) as exc:
        log_database_failure(
            logger,
            "delete_team",
            exc,
        )
        raise TeamDatabaseError(
            "Unable to delete the team right now."
        ) from None