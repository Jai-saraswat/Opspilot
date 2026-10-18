"""Central idempotency service for OpsPilot write operations."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from enum import Enum
from typing import Any, Callable
from uuid import UUID

import psycopg
from pydantic import ValidationError

from BACKEND.Postgres.gateway import get_connection
from BACKEND.Postgres.Operations.idempotency.errors import (
    IdempotencyAlreadyCompletedError,
    IdempotencyDatabaseError,
    IdempotencyKeyReuseError,
    IdempotencyRecordExpiredError,
    IdempotencyRecordNotFoundError,
    InvalidIdempotencyRecordError,
)
from BACKEND.Postgres.Operations.idempotency.reserve_idempotency_key import (
    reserve_idempotency_key,
)
from BACKEND.Postgres.Operations.idempotency.complete_idempotency_record import (
    complete_idempotency_record,
)
from BACKEND.Services.contracts import ServiceResponse, service_failure


DEFAULT_IDEMPOTENCY_TTL = timedelta(hours=24)


class _AbortTransaction(Exception):
    """Roll back the active transaction and return a service response."""

    def __init__(self, response: ServiceResponse) -> None:
        super().__init__("The service response requires a rollback.")
        self.response = response


def _json_value(value: Any) -> Any:
    """Convert supported values into deterministic JSON-compatible values."""

    if isinstance(value, UUID):
        return str(value)

    if isinstance(value, (datetime, date)):
        return value.isoformat()

    if isinstance(value, Decimal):
        return str(value)

    if isinstance(value, Enum):
        return _json_value(value.value)

    if isinstance(value, dict):
        if not all(isinstance(key, str) for key in value):
            raise ValueError(
                "Request payload dictionary keys must be strings."
            )

        return {
            key: _json_value(item)
            for key, item in value.items()
        }

    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]

    if value is None or isinstance(value, (str, int, float, bool)):
        return value

    raise TypeError(
        f"Unsupported request payload type: {type(value).__name__}"
    )


def hash_request(
    operation_name: str,
    payload: dict[str, Any],
) -> str:
    """Create a keyed SHA-256 digest for an operation and its payload."""

    if not isinstance(operation_name, str) or not operation_name.strip():
        raise ValueError("operation_name must be a non-empty string.")

    if not isinstance(payload, dict):
        raise TypeError("payload must be a dictionary.")

    secret = os.getenv("IDEMPOTENCY_HASH_SECRET", "")

    if len(secret) < 32:
        raise RuntimeError(
            "IDEMPOTENCY_HASH_SECRET must contain at least "
            "32 characters of random secret material."
        )

    canonical_payload = {
        "operation": operation_name,
        "payload": _json_value(payload),
    }

    encoded = json.dumps(
        canonical_payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")

    return hmac.new(
        secret.encode("utf-8"),
        encoded,
        hashlib.sha256,
    ).hexdigest()


def _failure(
    *,
    name: str,
    category: str,
    subcategory: str,
    description: str,
    code: str,
    message: str,
    status: int,
    retryable: bool = False,
) -> ServiceResponse:
    """Build a failure using the standard response contract."""

    return service_failure(
        name=name,
        category=category,
        subcategory=subcategory,
        description=description,
        code=code,
        message=message,
        http_status=status,
        retryable=retryable,
    )


def _run_operation(
    connection: psycopg.Connection,
    operation: Callable[[psycopg.Connection], ServiceResponse],
) -> ServiceResponse:
    """Run the callback and roll back if it returns a failure response."""

    response = operation(connection)

    if not isinstance(response, ServiceResponse):
        raise TypeError(
            "Idempotent operations must return ServiceResponse."
        )

    if not response.success:
        raise _AbortTransaction(response)

    return response


def execute_idempotently(
    *,
    user_id: UUID,
    idempotency_key: str | None,
    operation_name: str,
    category: str,
    subcategory: str,
    description: str,
    payload: dict[str, Any],
    operation: Callable[[psycopg.Connection], ServiceResponse],
    ttl: timedelta = DEFAULT_IDEMPOTENCY_TTL,
) -> ServiceResponse:
    """Execute a service callback with optional database-backed idempotency.

    The callback must pass the supplied connection to every database
    Operation participating in the same transaction.

    When a key is supplied:
      - A new request reserves its key and executes the callback.
      - A matching completed request replays its stored response.
      - Reusing a key for another payload returns HTTP 409.
      - A matching request currently in progress returns HTTP 409.
      - A failed ServiceResponse rolls back the transaction and is not cached.

    Without a key, the callback still runs transactionally and failed
    ServiceResponses still trigger a rollback.
    """

    if not isinstance(user_id, UUID):
        return _failure(
            name=operation_name,
            category=category,
            subcategory=subcategory,
            description=description,
            code="INVALID_ACTOR",
            message="A valid authenticated user is required.",
            status=401,
        )

    if not isinstance(ttl, timedelta) or ttl <= timedelta(0):
        raise ValueError("The idempotency TTL must be positive.")

    request_hash: str | None = None

    if idempotency_key is not None:
        if (
            not isinstance(idempotency_key, str)
            or not idempotency_key.strip()
            or len(idempotency_key) > 255
        ):
            return _failure(
                name=operation_name,
                category=category,
                subcategory=subcategory,
                description=description,
                code="INVALID_IDEMPOTENCY_KEY",
                message=(
                    "The idempotency key must contain "
                    "1 to 255 characters."
                ),
                status=400,
            )

        try:
            request_hash = hash_request(operation_name, payload)
        except (TypeError, ValueError):
            return _failure(
                name=operation_name,
                category=category,
                subcategory=subcategory,
                description=description,
                code="INVALID_REQUEST_PAYLOAD",
                message="The request payload cannot be processed safely.",
                status=400,
            )
        except RuntimeError:
            return _failure(
                name=operation_name,
                category=category,
                subcategory=subcategory,
                description=description,
                code="IDEMPOTENCY_CONFIGURATION_ERROR",
                message=(
                    "Secure idempotency is not configured correctly."
                ),
                status=500,
            )

    try:
        with get_connection() as connection:
            if idempotency_key is None:
                return _run_operation(connection, operation)

            reservation = reserve_idempotency_key(
                user_id=user_id,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                expires_at=datetime.now(timezone.utc) + ttl,
                connection=connection,
            )

            state = reservation.get("state")
            record = reservation.get("record") or {}

            if state == "replay":
                try:
                    return ServiceResponse.model_validate(
                        record["response_body"]
                    )
                except (KeyError, TypeError, ValidationError):
                    raise IdempotencyDatabaseError(
                        "The saved response is invalid."
                    ) from None

            if state == "in_progress":
                raise _AbortTransaction(
                    _failure(
                        name=operation_name,
                        category=category,
                        subcategory=subcategory,
                        description=description,
                        code="IDEMPOTENCY_IN_PROGRESS",
                        message=(
                            "A request using this idempotency key is still "
                            "being processed. Retry shortly with the same key."
                        ),
                        status=409,
                        retryable=True,
                    )
                )

            if state != "reserved":
                raise IdempotencyDatabaseError(
                    "The idempotency operation returned an unknown state."
                )

            response = _run_operation(connection, operation)

            complete_idempotency_record(
                user_id=user_id,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                response_status=response.http_status,
                response_body=response.model_dump(mode="json"),
                connection=connection,
            )

            return response

    except _AbortTransaction as abort:
        return abort.response

    except IdempotencyKeyReuseError:
        return _failure(
            name=operation_name,
            category=category,
            subcategory=subcategory,
            description=description,
            code="IDEMPOTENCY_KEY_REUSED",
            message=(
                "This idempotency key was already used for a different "
                "request. Use a new key for a different operation."
            ),
            status=409,
        )

    except (
        InvalidIdempotencyRecordError,
        IdempotencyDatabaseError,
        IdempotencyRecordExpiredError,
        IdempotencyRecordNotFoundError,
        IdempotencyAlreadyCompletedError,
    ):
        return _failure(
            name=operation_name,
            category=category,
            subcategory=subcategory,
            description=description,
            code="IDEMPOTENCY_STORAGE_ERROR",
            message=(
                "The request could not be processed safely because "
                "idempotency storage failed."
            ),
            status=500,
            retryable=True,
        )