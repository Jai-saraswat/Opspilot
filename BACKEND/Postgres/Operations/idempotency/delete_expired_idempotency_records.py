"""Delete expired idempotency records in bounded batches."""

from __future__ import annotations

import logging

import psycopg

from BACKEND.Postgres.Operations._db import (
    connection_scope,
    log_database_failure,
)
from BACKEND.Postgres.Operations.idempotency.errors import (
    IdempotencyDatabaseError,
)

logger = logging.getLogger(__name__)


def delete_expired_idempotency_records(
    *,
    batch_size: int = 500,
    connection: psycopg.Connection | None = None,
) -> int:
    """Delete up to batch_size expired records and return the count."""
    if not 1 <= batch_size <= 5000:
        raise ValueError("Batch size must be between 1 and 5000.")

    query = """
        WITH expired AS (
            SELECT id
            FROM idempotency_records
            WHERE expires_at <= CURRENT_TIMESTAMP
            ORDER BY expires_at ASC, id ASC
            LIMIT %s
            FOR UPDATE SKIP LOCKED
        )
        DELETE FROM idempotency_records AS records
        USING expired
        WHERE records.id = expired.id
        RETURNING records.id;
    """

    try:
        with connection_scope(connection) as conn:
            with conn.cursor() as cursor:
                cursor.execute(query, (batch_size,))
                return len(cursor.fetchall())

    except (psycopg.Error, RuntimeError) as exc:
        log_database_failure(
            logger,
            "delete_expired_idempotency_records",
            exc,
        )
        raise IdempotencyDatabaseError(
            "Unable to clean up expired idempotency records right now."
        ) from None