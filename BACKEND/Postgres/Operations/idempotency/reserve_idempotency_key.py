"""Atomically reserve an idempotency key or retrieve its existing result."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import psycopg
from psycopg import errors as pg_errors
from psycopg.rows import dict_row

from BACKEND.Postgres.Operations._db import (
    connection_scope,
    log_database_failure,
)
from BACKEND.Postgres.Operations.idempotency.errors import (
    IdempotencyDatabaseError,
    IdempotencyKeyReuseError,
    InvalidIdempotencyRecordError,
)

logger = logging.getLogger(__name__)

_HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_MAX_RESERVATION_ATTEMPTS = 3


def reserve_idempotency_key(
    *,
    user_id: UUID,
    idempotency_key: str,
    request_hash: str,
    expires_at: datetime,
    connection: psycopg.Connection | None = None,
) -> dict[str, Any]:
    """Reserve a key or return the state of its existing request.

    Returns:
        {
            "state": "reserved" | "replay" | "in_progress",
            "record": {...}
        }

    request_hash must be a lowercase SHA-256 hex digest of a canonical
    representation of the request.

    Pass a shared connection when reservation, business changes, and
    response persistence must be part of one transaction. Without a
    supplied connection, this operation manages its own transaction.
    """
    if not isinstance(idempotency_key, str) or not (
        1 <= len(idempotency_key) <= 255
    ):
        raise InvalidIdempotencyRecordError(
            "The idempotency key must contain between 1 and 255 characters."
        )

    if not isinstance(request_hash, str) or not _HASH_PATTERN.fullmatch(
        request_hash
    ):
        raise InvalidIdempotencyRecordError(
            "The request hash must be a 64-character lowercase SHA-256 digest."
        )

    if not isinstance(expires_at, datetime):
        raise InvalidIdempotencyRecordError(
            "The expiry timestamp must be a datetime value."
        )

    if expires_at.tzinfo is None or expires_at.utcoffset() is None:
        raise InvalidIdempotencyRecordError(
            "The expiry timestamp must include a timezone."
        )

    if expires_at <= datetime.now(timezone.utc):
        raise InvalidIdempotencyRecordError(
            "The expiry timestamp must be in the future."
        )

    reserve_query = """
        INSERT INTO idempotency_records (
            user_id,
            idempotency_key,
            request_hash,
            created_at,
            expires_at
        )
        VALUES (
            %s,
            %s,
            %s,
            clock_timestamp(),
            %s
        )
        ON CONFLICT (user_id, idempotency_key)
        DO UPDATE SET
            request_hash = EXCLUDED.request_hash,
            response_status = NULL,
            response_body = NULL,
            created_at = clock_timestamp(),
            expires_at = EXCLUDED.expires_at
        WHERE idempotency_records.expires_at <= clock_timestamp()
          AND EXCLUDED.expires_at > clock_timestamp()
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

    get_existing_query = """
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
                for _ in range(_MAX_RESERVATION_ATTEMPTS):
                    cursor.execute(
                        reserve_query,
                        (
                            user_id,
                            idempotency_key,
                            request_hash,
                            expires_at,
                        ),
                    )
                    row = cursor.fetchone()

                    if row is not None:
                        return {
                            "state": "reserved",
                            "record": dict(row),
                        }

                    # An active record prevented reservation, or the record's
                    # state changed while this request was waiting.
                    cursor.execute(
                        get_existing_query,
                        (user_id, idempotency_key),
                    )
                    existing = cursor.fetchone()

                    if existing is None:
                        if expires_at <= datetime.now(timezone.utc):
                            raise InvalidIdempotencyRecordError(
                                "The expiry timestamp elapsed before the "
                                "reservation could be created."
                            )

                        raise IdempotencyDatabaseError(
                            "Unable to determine the idempotency-key status."
                        )

                    record = dict(existing)
                    is_expired = record.pop("is_expired")

                    # Retry reservation when the old key has expired.
                    # Check expiry before the hash: an expired key can be
                    # reused for a different request.
                    if is_expired:
                        if expires_at <= datetime.now(timezone.utc):
                            raise InvalidIdempotencyRecordError(
                                "The expiry timestamp elapsed before the "
                                "reservation could be renewed."
                            )
                        continue

                    if record["request_hash"] != request_hash:
                        raise IdempotencyKeyReuseError(
                            "This idempotency key was already used for "
                            "a different request."
                        )

                    # response_status indicates completion. The response
                    # body may legitimately contain JSON null.
                    if record["response_status"] is not None:
                        return {
                            "state": "replay",
                            "record": record,
                        }

                    return {
                        "state": "in_progress",
                        "record": record,
                    }

                raise IdempotencyDatabaseError(
                    "The reservation state kept changing during concurrent "
                    "requests. Please retry."
                )

    except (
        IdempotencyKeyReuseError,
        InvalidIdempotencyRecordError,
        IdempotencyDatabaseError,
    ):
        raise

    except pg_errors.ForeignKeyViolation as exc:
        log_database_failure(
            logger,
            "reserve_idempotency_key",
            exc,
        )
        raise IdempotencyDatabaseError(
            "The user associated with this request does not exist."
        ) from None

    except pg_errors.CheckViolation as exc:
        log_database_failure(
            logger,
            "reserve_idempotency_key",
            exc,
        )
        raise InvalidIdempotencyRecordError(
            "The idempotency record violates a database constraint."
        ) from None

    except (psycopg.Error, RuntimeError) as exc:
        log_database_failure(
            logger,
            "reserve_idempotency_key",
            exc,
        )
        raise IdempotencyDatabaseError(
            "Unable to reserve the idempotency key right now."
        ) from None