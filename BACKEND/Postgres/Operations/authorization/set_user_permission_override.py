"""Create or update a user's permission override."""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

import psycopg
from psycopg import errors as pg_errors
from psycopg.rows import dict_row

from BACKEND.Postgres.Operations._db import connection_scope, log_database_failure
from BACKEND.Postgres.Operations.authorization.errors import (
    AuthorizationDatabaseError,
    AuthorizationRelatedRecordNotFoundError,
    InvalidAuthorizationRecordError,
)

logger = logging.getLogger(__name__)


def set_user_permission_override(
    *,
    user_id: UUID,
    permission_id: UUID,
    effect: str,
    team_id: UUID | None = None,
    assigned_by: UUID | None = None,
    connection: psycopg.Connection | None = None,
) -> dict[str, Any]:
    """Upsert an allow/deny override and return the stored record."""
    query = """
        INSERT INTO user_permission_overrides (
            user_id,
            permission_id,
            team_id,
            effect,
            assigned_by
        )
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT ON CONSTRAINT uq_user_permission_global
        DO UPDATE SET
            effect = EXCLUDED.effect,
            assigned_by = EXCLUDED.assigned_by,
            created_at = CURRENT_TIMESTAMP
        RETURNING
            id,
            user_id,
            permission_id,
            team_id,
            effect,
            assigned_by,
            created_at;
    """

    try:
        with connection_scope(connection) as conn:
            with conn.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    query,
                    (user_id, permission_id, team_id, effect, assigned_by),
                )
                row = cursor.fetchone()

                if row is None:
                    raise AuthorizationDatabaseError(
                        "The permission override could not be saved."
                    )

                return dict(row)

    except pg_errors.ForeignKeyViolation:
        raise AuthorizationRelatedRecordNotFoundError(
            "A referenced user, permission, team, or assigning user does not exist."
        ) from None

    except pg_errors.CheckViolation:
        raise InvalidAuthorizationRecordError(
            "The override effect must be 'allow' or 'deny'."
        ) from None

    except (psycopg.Error, RuntimeError) as exc:
        log_database_failure(
            logger,
            "set_user_permission_override",
            exc,
        )
        raise AuthorizationDatabaseError(
            "Unable to save the permission override."
        ) from None