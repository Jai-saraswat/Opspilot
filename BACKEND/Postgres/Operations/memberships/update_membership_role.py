"""Update a user's role within a team."""

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
    MembershipDatabaseError,
)

logger = logging.getLogger(__name__)


def update_membership_role(
    team_id: UUID,
    user_id: UUID,
    role: str,
    *,
    connection: psycopg.Connection | None = None,
) -> dict[str, Any] | None:
    """Update the membership role, or return None if not found."""
    query = """
        UPDATE team_memberships
        SET role = %s
        WHERE team_id = %s AND user_id = %s
        RETURNING id, team_id, user_id, role, joined_at;
    """

    try:
        with connection_scope(connection) as conn:
            with conn.cursor(row_factory=dict_row) as cursor:
                cursor.execute(query, (role, team_id, user_id))
                row = cursor.fetchone()

                return dict(row) if row is not None else None

    except pg_errors.CheckViolation as exc:
        log_database_failure(logger, "update_membership_role", exc)
        raise InvalidMembershipRecordError(
            "The membership role must be lead, member, or approver."
        ) from None

    except (psycopg.Error, RuntimeError) as exc:
        log_database_failure(logger, "update_membership_role", exc)
        raise MembershipDatabaseError(
            "Unable to update the membership role right now."
        ) from None