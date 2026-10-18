"""Retry a rejected approval request without creating a new row."""

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
from BACKEND.Postgres.Operations.approvals.errors import (
    ApprovalDatabaseError,
    InvalidApprovalRecordError,
)

logger = logging.getLogger(__name__)


def retry_rejected_approval_request(
    approval_request_id: UUID,
    *,
    connection: psycopg.Connection | None = None,
) -> dict[str, Any] | None:
    """Reset rejected -> pending, or return None if it is no longer rejected."""
    query = """
        UPDATE work_item_approval_requests
        SET
            status = 'pending',
            decision_reason = NULL,
            decided_at = NULL,
            requested_at = clock_timestamp()
        WHERE id = %s
          AND status = 'rejected'
        RETURNING
            id,
            work_item_id,
            requested_by,
            approver_id,
            status,
            decision_reason,
            requested_at,
            decided_at;
    """

    try:
        with connection_scope(connection) as conn:
            with conn.cursor(row_factory=dict_row) as cursor:
                cursor.execute(query, (approval_request_id,))
                row = cursor.fetchone()

                return dict(row) if row is not None else None

    except pg_errors.CheckViolation as exc:
        log_database_failure(
            logger,
            "retry_rejected_approval_request",
            exc,
        )
        raise InvalidApprovalRecordError(
            "The approval retry violates a database constraint."
        ) from None

    except (psycopg.Error, RuntimeError) as exc:
        log_database_failure(
            logger,
            "retry_rejected_approval_request",
            exc,
        )
        raise ApprovalDatabaseError(
            "Unable to retry the rejected approval request right now."
        ) from None