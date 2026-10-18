"""Create a login session in PostgreSQL."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any
from uuid import UUID

import psycopg
from psycopg import errors as pg_errors
from psycopg.rows import dict_row

from BACKEND.Postgres.Operations._db import (
    connection_scope,
    log_database_failure,
)
from BACKEND.Postgres.Operations.sessions.errors import (
    InvalidSessionRecordError,
    SessionDatabaseError,
    SessionUserNotFoundError,
)

logger = logging.getLogger(__name__)


def create_session(
    *,
    user_id: UUID,
    refresh_token_hash: str,
    expires_at: datetime,
    connection: psycopg.Connection | None = None,
) -> dict[str, Any]:
    """Persist a session and return its non-sensitive fields."""
    query = """
        INSERT INTO login_sessions (
            user_id,
            refresh_token_hash,
            expires_at
        )
        VALUES (%s, %s, %s)
        RETURNING id, user_id, expires_at, revoked_at, created_at;
    """

    try:
        with connection_scope(connection) as conn:
            with conn.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    query,
                    (user_id, refresh_token_hash, expires_at),
                )
                row = cursor.fetchone()

                if row is None:
                    raise SessionDatabaseError(
                        "The login session could not be created."
                    )

                return dict(row)

    except pg_errors.ForeignKeyViolation as exc:
        if exc.diag.constraint_name == "login_sessions_user_id_fkey":
            raise SessionUserNotFoundError(
                "The referenced user does not exist."
            ) from None

        log_database_failure(logger, "create_session", exc)
        raise SessionDatabaseError(
            "Unable to create the login session."
        ) from None

    except pg_errors.UniqueViolation as exc:
        log_database_failure(logger, "create_session", exc)
        raise SessionDatabaseError(
            "The login session could not be created because of a database constraint."
        ) from None

    except pg_errors.CheckViolation as exc:
        log_database_failure(logger, "create_session", exc)
        raise InvalidSessionRecordError(
            "The session expiry or revocation values are invalid."
        ) from None

    except (psycopg.Error, RuntimeError) as exc:
        log_database_failure(logger, "create_session", exc)
        raise SessionDatabaseError(
            "Unable to create the login session right now."
        ) from None