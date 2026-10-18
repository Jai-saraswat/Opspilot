"""Store the final response for an idempotency reservation."""

from __future__ import annotations

import logging
import re
from typing import Any
from uuid import UUID

import psycopg
from psycopg import errors as pg_errors
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from BACKEND.Postgres.Operations._db import (
    connection_scope,
    log_database_failure,
)
from BACKEND.Postgres.Operations.idempotency.errors import (
    IdempotencyAlreadyCompletedError,
    IdempotencyDatabaseError,
    IdempotencyKeyReuseError,
    IdempotencyRecordExpiredError,
    IdempotencyRecordNotFoundError,
    InvalidIdempotencyRecordError,
)

logger = logging.getLogger(__name__)

_HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def complete_idempotency_record(
    *,
    user_id: UUID,
    idempotency_key: str,
    request_hash: str,
    response_status: int,
    response_body: Any,
    connection: psycopg.Connection | None = None,
) -> dict[str, Any]:
    """Persist the response for an active idempotency reservation.

    The response body is encoded as JSONB. Python None is stored as the
    JSON value null, not SQL NULL. Therefore, response_status determines
    whether the record has been completed.

    If a connection is supplied, its transaction is owned by the caller.
    Otherwise, connection_scope manages the connection and transaction.
    """
    if not idempotency_key or len(idempotency_key) > 255:
        raise InvalidIdempotencyRecordError(
            "The idempotency key must contain between 1 and 255 characters."
        )

    if not isinstance(request_hash, str) or not _HASH_PATTERN.fullmatch(
        request_hash
    ):
        raise InvalidIdempotencyRecordError(
            "The request hash must be a 64-character lowercase SHA-256 digest."
        )

    if (
        not isinstance(response_status, int)
        or isinstance(response_status, bool)
        or not 100 <= response_status <= 599
    ):
        raise InvalidIdempotencyRecordError(
            "The response status must be an integer between 100 and 599."
        )

    update_query = """
        UPDATE idempotency_records
        SET
            response_status = %s,
            response_body = %s
        WHERE user_id = %s
          AND idempotency_key = %s
          AND request_hash = %s
          AND response_status IS NULL
          AND response_body IS NULL
          AND expires_at > clock_timestamp()
        RETURNING
            id,
            user_id,
            idempotency_key,
            request_hash,
            response_status,
            response_body,
            created_at,
            expires_at;
    """

    lookup_query = """
        SELECT
            id,
            user_id,
            idempotency_key,
            request_hash,
            response_status,
            response_body,
            created_at,
            expires_at,
            expires_at <= clock_timestamp() AS is_expired
        FROM idempotency_records
        WHERE user_id = %s
          AND idempotency_key = %s;
    """

    try:
        with connection_scope(connection) as conn:
            with conn.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    update_query,
                    (
                        response_status,
                        Jsonb(response_body),
                        user_id,
                        idempotency_key,
                        request_hash,
                    ),
                )
                row = cursor.fetchone()

                if row is not None:
                    return dict(row)

                cursor.execute(
                    lookup_query,
                    (user_id, idempotency_key),
                )
                existing = cursor.fetchone()

                if existing is None:
                    raise IdempotencyRecordNotFoundError(
                        "The idempotency reservation does not exist."
                    )

                record = dict(existing)

                if record["request_hash"] != request_hash:
                    raise IdempotencyKeyReuseError(
                        "This idempotency key belongs to a different request."
                    )

                # Check completion before expiry so we can distinguish an
                # already-completed reservation from an incomplete expired one.
                if record["response_status"] is not None:
                    raise IdempotencyAlreadyCompletedError(
                        "The idempotency record already has a saved response."
                    )

                if record["is_expired"]:
                    raise IdempotencyRecordExpiredError(
                        "The idempotency reservation has expired."
                    )

                raise IdempotencyDatabaseError(
                    "The reservation could not be completed because its state changed."
                )

    except (
        IdempotencyRecordNotFoundError,
        IdempotencyKeyReuseError,
        IdempotencyAlreadyCompletedError,
        IdempotencyRecordExpiredError,
        InvalidIdempotencyRecordError,
        IdempotencyDatabaseError,
    ):
        raise

    except pg_errors.CheckViolation as exc:
        log_database_failure(
            logger,
            "complete_idempotency_record",
            exc,
        )
        raise InvalidIdempotencyRecordError(
            "The response data violates an idempotency-record constraint."
        ) from None

    except (psycopg.Error, RuntimeError) as exc:
        log_database_failure(
            logger,
            "complete_idempotency_record",
            exc,
        )
        raise IdempotencyDatabaseError(
            "Unable to save the idempotency response right now."
        ) from None