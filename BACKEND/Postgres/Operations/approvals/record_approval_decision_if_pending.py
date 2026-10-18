"""Record an approval decision only if the request is still pending."""

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


def record_approval_decision_if_pending(
    approval_request_id: UUID,
    decision: str,
    *,
    decision_reason: str | None = None,
    connection: psycopg.Connection | None = None,
) -> dict[str, Any] | None:
    """Record an approval or rejection for a pending request.

    Args:
        approval_request_id: The request to decide.
        decision: Must be 'approved' or 'rejected'.
        decision_reason: Optional explanation for the decision.
        connection: Optional transaction connection owned by the caller.

    Returns:
        The updated approval record, or None if the request is missing
        or no longer pending.

    The service must validate the actor's permissions and coordinate this
    update with the work-item status and activity-history changes in the
    same transaction.
    """
    if decision not in {"approved", "rejected"}:
        raise InvalidApprovalRecordError(
            "Decision must be 'approved' or 'rejected'."
        )

    query = """
        UPDATE work_item_approval_requests
        SET
            status = %s,
            decision_reason = %s,
            decided_at = CURRENT_TIMESTAMP
        WHERE id = %s
          AND status = 'pending'
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
                cursor.execute(
                    query,
                    (decision, decision_reason, approval_request_id),
                )
                row = cursor.fetchone()

                return dict(row) if row is not None else None

    except pg_errors.CheckViolation as exc:
        log_database_failure(
            logger,
            "record_approval_decision_if_pending",
            exc,
        )
        raise InvalidApprovalRecordError(
            "The approval decision violates a database constraint."
        ) from None

    except (psycopg.Error, RuntimeError) as exc:
        log_database_failure(
            logger,
            "record_approval_decision_if_pending",
            exc,
        )
        raise ApprovalDatabaseError(
            "Unable to record the approval decision right now."
        ) from None