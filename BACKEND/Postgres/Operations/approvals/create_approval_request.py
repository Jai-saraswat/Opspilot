"""Create a work-item approval request."""

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


def create_approval_request(
    *,
    work_item_id: UUID,
    requested_by: UUID,
    approver_id: UUID | None = None,
    connection: psycopg.Connection | None = None,
) -> dict[str, Any]:
    """Insert a pending approval request and return its record."""
    query = """
        INSERT INTO work_item_approval_requests (
            work_item_id,
            requested_by,
            approver_id
        )
        VALUES (%s, %s, %s)
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
                    (work_item_id, requested_by, approver_id),
                )
                row = cursor.fetchone()

                if row is None:
                    raise ApprovalDatabaseError(
                        "The approval request could not be created."
                    )

                return dict(row)

    except pg_errors.ForeignKeyViolation as exc:
        constraint = exc.diag.constraint_name

        if constraint == "work_item_approval_requests_work_item_id_fkey":
            raise ApprovalRelatedRecordNotFoundError(
                "The referenced work item does not exist."
            ) from None

        if constraint == "work_item_approval_requests_requested_by_fkey":
            raise ApprovalRelatedRecordNotFoundError(
                "The requesting user does not exist."
            ) from None

        if constraint == "work_item_approval_requests_approver_id_fkey":
            raise ApprovalRelatedRecordNotFoundError(
                "The specified approver does not exist."
            ) from None

        log_database_failure(logger, "create_approval_request", exc)
        raise ApprovalDatabaseError(
            "A related record prevented the approval request from being created."
        ) from None

    except (psycopg.Error, RuntimeError) as exc:
        log_database_failure(logger, "create_approval_request", exc)
        raise ApprovalDatabaseError(
            "Unable to create the approval request right now."
        ) from None