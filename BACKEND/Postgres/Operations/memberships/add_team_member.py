"""Insert a team membership into PostgreSQL."""

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
from BACKEND.Postgres.Operations.memberships.errors import (
    InvalidMembershipRecordError,
    MembershipAlreadyExistsError,
    MembershipDatabaseError,
    MembershipRelatedRecordNotFoundError,
)

logger = logging.getLogger(__name__)


def add_team_member(
    *,
    team_id: UUID,
    user_id: UUID,
    role: str = "member",
    connection: psycopg.Connection | None = None,
) -> dict[str, Any]:
    """Create a membership and return the inserted record."""
    query = """
        INSERT INTO team_memberships (team_id, user_id, role)
        VALUES (%s, %s, %s)
        RETURNING id, team_id, user_id, role, joined_at;
    """

    try:
        with connection_scope(connection) as conn:
            with conn.cursor(row_factory=dict_row) as cursor:
                cursor.execute(query, (team_id, user_id, role))
                row = cursor.fetchone()

                if row is None:
                    raise MembershipDatabaseError(
                        "The membership could not be created."
                    )

                return dict(row)

    except pg_errors.UniqueViolation as exc:
        if exc.diag.constraint_name == "uq_team_memberships_team_user":
            raise MembershipAlreadyExistsError(
                "This user is already a member of the team."
            ) from None

        log_database_failure(logger, "add_team_member", exc)
        raise MembershipDatabaseError(
            "Unable to create the membership because of a database constraint."
        ) from None

    except pg_errors.ForeignKeyViolation as exc:
        constraint = exc.diag.constraint_name

        if constraint == "team_memberships_team_id_fkey":
            raise MembershipRelatedRecordNotFoundError(
                "The specified team does not exist."
            ) from None

        if constraint == "team_memberships_user_id_fkey":
            raise MembershipRelatedRecordNotFoundError(
                "The specified user does not exist."
            ) from None

        log_database_failure(logger, "add_team_member", exc)
        raise MembershipDatabaseError(
            "A referenced record does not exist."
        ) from None

    except pg_errors.CheckViolation as exc:
        log_database_failure(logger, "add_team_member", exc)
        raise InvalidMembershipRecordError(
            "The supplied membership role is invalid."
        ) from None

    except (psycopg.Error, RuntimeError) as exc:
        log_database_failure(logger, "add_team_member", exc)
        raise MembershipDatabaseError(
            "Unable to add the team member right now."
        ) from None