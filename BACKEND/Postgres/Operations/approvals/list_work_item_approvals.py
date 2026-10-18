"""List approval requests associated with a work item."""

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
from BACKEND.Postgres.Operations.approvals.errors import ApprovalDatabaseError

logger = logging.getLogger(__name__)


def list_work_item_approvals(
    work_item_id: UUID,
    *,
    limit: int = 50,
    offset: int = 0,
    status: str | None = None,
    connection: psycopg.Connection | None = None,
) -> dict[str, Any]:
    """Return paginated approval history for a work item."""
    if not 1 <= limit <= 100:
        raise ValueError("Limit must be between 1 and 100.")

    if offset < 0:
        raise ValueError("Offset cannot be negative.")

    conditions = ["a.work_item_id = %s"]
    parameters: list[Any] = [work_item_id]

    if status is not None:
        conditions.append("a.status = %s")
        parameters.append(status)

    where_clause = "WHERE " + " AND ".join(conditions)

    count_query = f"""
        SELECT COUNT(*) AS total
        FROM work_item_approval_requests AS a
        {where_clause};
    """

    list_query = f"""
        SELECT
            a.id,
            a.work_item_id,
            a.requested_by,
            a.approver_id,
            a.status,
            a.decision_reason,
            a.requested_at,
            a.decided_at,
            requester.full_name AS requester_name,
            approver.full_name AS approver_name
        FROM work_item_approval_requests AS a
        JOIN users AS requester ON requester.id = a.requested_by
        LEFT JOIN users AS approver ON approver.id = a.approver_id
        {where_clause}
        ORDER BY a.requested_at DESC, a.id DESC
        LIMIT %s OFFSET %s;
    """

    try:
        with connection_scope(connection) as conn:
            with conn.cursor(row_factory=dict_row) as cursor:
                cursor.execute(count_query, tuple(parameters))
                total = cursor.fetchone()["total"]

                cursor.execute(
                    list_query,
                    (*parameters, limit, offset),
                )
                rows = cursor.fetchall()

                return {
                    "items": [dict(row) for row in rows],
                    "total": total,
                    "limit": limit,
                    "offset": offset,
                }

    except (psycopg.Error, RuntimeError) as exc:
        log_database_failure(
            logger,
            "list_work_item_approvals",
            exc,
        )
        raise ApprovalDatabaseError(
            "Unable to retrieve approval history right now."
        ) from None