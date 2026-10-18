"""Assign an approver to a pending approval request."""

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
    ApprovalRelatedRecordNotFoundError,
)

logger = logging.getLogger(__name__)


def assign_approval_approver(
    approval_request_id: UUID,
    approver_id: UUID | None,
    *,
    connection: psycopg.Connection | None = None,
) -> dict[str, Any] | None:
    """Update approver only while request status is pending.

    Returns None if the request doesn't exist or is no longer pending.
    The service must verify that the approver is eligible for the request.
    """
    query = """
        UPDATE work_item_approval_requests
        SET approver_id = %s
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
                    (approver_id, approval_request_id),
                )
                row = cursor.fetchone()

                return dict(row) if row is not None else None

    except pg_errors.ForeignKeyViolation as exc:
        if exc.diag.constraint_name == (
            "work_item_approval_requests_approver_id_fkey"
        ):
            raise ApprovalRelatedRecordNotFoundError(
                "The specified approver does not exist."
            ) from None

        log_database_failure(
            logger,
            "assign_approval_approver",
            exc,
        )
        raise ApprovalDatabaseError(
            "Unable to assign the approver right now."
        ) from None

    except (psycopg.Error, RuntimeError) as exc:
        log_database_failure(
            logger,
            "assign_approval_approver",
            exc,
        )
        raise ApprovalDatabaseError(
            "Unable to assign the approver right now."
        ) from None