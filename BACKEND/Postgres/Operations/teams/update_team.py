"""Update selected fields of a team."""

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
    TeamDatabaseError,
)

logger = logging.getLogger(__name__)


class _Unset:
    """Sentinel indicating that a field was not supplied."""


UNSET = _Unset()


def update_team(
    team_id: UUID,
    *,
    name: str | None = None,
    description: str | None | _Unset = UNSET,
    connection: psycopg.Connection | None = None,
) -> dict[str, Any] | None:
    """Update supplied team fields.

    Returns the updated team, or None if no team with the ID exists.

    `name=None` means unchanged.
    `description=UNSET` means unchanged.
    `description=None` means clear the description.
    """
    updates: list[str] = []
    parameters: list[Any] = []

    if name is not None:
        updates.append("name = %s")
        parameters.append(name)

    if not isinstance(description, _Unset):
        updates.append("description = %s")
        parameters.append(description)

    if not updates:
        raise InvalidTeamRecordError(
            "Provide at least one team field to update."
        )

    updates.append("updated_at = CURRENT_TIMESTAMP")
    parameters.append(team_id)

    query = f"""
        UPDATE teams
        SET {", ".join(updates)}
        WHERE id = %s
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
                cursor.execute(query, tuple(parameters))
                row = cursor.fetchone()

                return dict(row) if row is not None else None

    except pg_errors.UniqueViolation as exc:
        if exc.diag.constraint_name == "uq_teams_name":
            raise TeamAlreadyExistsError(
                "A team with this name already exists."
            ) from None

        log_database_failure(logger, "update_team", exc)
        raise TeamDatabaseError(
            "Unable to update the team right now."
        ) from None

    except pg_errors.CheckViolation as exc:
        log_database_failure(logger, "update_team", exc)
        raise InvalidTeamRecordError(
            "The supplied team data is invalid."
        ) from None

    except (psycopg.Error, RuntimeError) as exc:
        log_database_failure(logger, "update_team", exc)
        raise TeamDatabaseError(
            "Unable to update the team right now."
        ) from None