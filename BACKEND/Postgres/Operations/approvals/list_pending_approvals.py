"""List pending approval requests with optional team scoping."""

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


def list_pending_approvals(
    *,
    limit: int = 50,
    offset: int = 0,
    approver_id: UUID | None = None,
    unassigned_only: bool = False,
    team_ids: list[UUID] | None = None,
    connection: psycopg.Connection | None = None,
) -> dict[str, Any]:
    """Return a paginated pending queue.

    team_ids=None means no team filter.
    team_ids=[] means no eligible teams and returns an empty page.
    """
    if not 1 <= limit <= 100:
        raise ValueError("Limit must be between 1 and 100.")

    if offset < 0:
        raise ValueError("Offset cannot be negative.")

    if unassigned_only and approver_id is not None:
        raise ValueError(
            "Specify approver_id or unassigned_only, not both."
        )

    if team_ids is not None and not team_ids:
        return {
            "items": [],
            "total": 0,
            "limit": limit,
            "offset": offset,
        }

    conditions = ["a.status = 'pending'"]
    parameters: list[Any] = []

    if unassigned_only:
        conditions.append("a.approver_id IS NULL")
    elif approver_id is not None:
        conditions.append("a.approver_id = %s")
        parameters.append(approver_id)

    if team_ids is not None:
        conditions.append("w.team_id = ANY(%s::uuid[])")
        parameters.append(team_ids)

    where_clause = "WHERE " + " AND ".join(conditions)

    count_query = f"""
        SELECT COUNT(*) AS total
        FROM work_item_approval_requests AS a
        JOIN work_items AS w ON w.id = a.work_item_id
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
            w.team_id,
            w.title AS work_item_title,
            w.priority AS work_item_priority,
            requester.full_name AS requester_name,
            approver.full_name AS approver_name
        FROM work_item_approval_requests AS a
        JOIN work_items AS w ON w.id = a.work_item_id
        JOIN users AS requester ON requester.id = a.requested_by
        LEFT JOIN users AS approver ON approver.id = a.approver_id
        {where_clause}
        ORDER BY a.requested_at ASC, a.id ASC
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
        log_database_failure(logger, "list_pending_approvals", exc)
        raise ApprovalDatabaseError(
            "Unable to retrieve pending approvals right now."
        ) from None