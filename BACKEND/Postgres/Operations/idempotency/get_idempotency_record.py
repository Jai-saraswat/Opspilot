"""Retrieve an idempotency record by user and key."""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

from BACKEND.Postgres.Operations._db import (
    connection_scope,
    log_database_failure,
)
from BACKEND.Postgres.Operations.idempotency.errors import (
    IdempotencyDatabaseError,
)

logger = logging.getLogger(__name__)


def get_idempotency_record(
    user_id: UUID,
    idempotency_key: str,
    *,
    connection: psycopg.Connection | None = None,
) -> dict[str, Any] | None:
    """Return the record, or None if no record exists."""
    query = """
        SELECT
            id,
            user_id,
            idempotency_key,
            request_hash,
            response_status,
            response_body,
            created_at,
            expires_at
        FROM idempotency_records
        WHERE user_id = %s
          AND idempotency_key = %s;
    """

    try:
        with connection_scope(connection) as conn:
            with conn.cursor(row_factory=dict_row) as cursor:
                cursor.execute(query, (user_id, idempotency_key))
                row = cursor.fetchone()

                return dict(row) if row is not None else None

    except (psycopg.Error, RuntimeError) as exc:
        log_database_failure(logger, "get_idempotency_record", exc)
        raise IdempotencyDatabaseError(
            "Unable to retrieve the idempotency record right now."
        ) from None