"""Insert a team into PostgreSQL."""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

import psycopg
from psycopg import errors as pg_errors
from psycopg.rows import dict_row

from BACKEND.Postgres.Operations._db import (
    connection_scope,
    log_database_failure,
)
from BACKEND.Postgres.Operations.teams.errors import (
    InvalidTeamRecordError,
    TeamAlreadyExistsError,
    TeamCreatorNotFoundError,
    TeamDatabaseError,
)

logger = logging.getLogger(__name__)


def create_team(
    *,
    name: str,
    created_by: UUID,
    description: str | None = None,
    connection: psycopg.Connection | None = None,
) -> dict[str, Any]:
    """Create a team and return its database-generated fields."""
    query = """
        INSERT INTO teams (name, description, created_by)
        VALUES (%s, %s, %s)
        RETURNING
            id,
            name,
            description,
            created_by,
            created_at,
            updated_at;
    """

    try:
        with connection_scope(connection) as conn:
            with conn.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    query,
                    (name, description, created_by),
                )
                row = cursor.fetchone()

                if row is None:
                    raise TeamDatabaseError(
                        "The team could not be created. Please try again."
                    )

                return dict(row)

    except pg_errors.UniqueViolation as exc:
        if exc.diag.constraint_name == "uq_teams_name":
            raise TeamAlreadyExistsError(
                "A team with this name already exists."
            ) from None

        log_database_failure(logger, "create_team", exc)
        raise TeamDatabaseError(
            "The team could not be created because of a database constraint."
        ) from None

    except pg_errors.CheckViolation as exc:
        log_database_failure(logger, "create_team", exc)
        raise InvalidTeamRecordError(
            "The supplied team data is invalid."
        ) from None

    except pg_errors.ForeignKeyViolation as exc:
        if exc.diag.constraint_name == "teams_created_by_fkey":
            raise TeamCreatorNotFoundError(
                "The specified team creator does not exist."
            ) from None

        log_database_failure(logger, "create_team", exc)
        raise TeamDatabaseError(
            "The team could not be created because a related record is missing."
        ) from None

    except (psycopg.Error, RuntimeError) as exc:
        log_database_failure(logger, "create_team", exc)
        raise TeamDatabaseError(
            "Unable to create the team right now. Please try again."
        ) from None