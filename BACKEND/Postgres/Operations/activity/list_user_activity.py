"""List activity records associated with a user."""

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
from BACKEND.Postgres.Operations.activity.errors import ActivityDatabaseError

logger = logging.getLogger(__name__)


def list_user_activity(
    actor_id: UUID,
    *,
    limit: int = 50,
    offset: int = 0,
    action: str | None = None,
    visible_team_ids: list[UUID] | None = None,
    connection: psycopg.Connection | None = None,
) -> dict[str, Any]:
    """Return a paginated history of activity associated with an actor.

    visible_team_ids=None means no team filter and should only be used
    by a caller that is authorized to view the complete actor feed.

    An empty list returns no results. A populated list limits the
    activity to work items belonging to those teams.
    """
    if not 1 <= limit <= 100:
        raise ValueError("Limit must be between 1 and 100.")

    if offset < 0:
        raise ValueError("Offset cannot be negative.")

    if visible_team_ids is not None and not visible_team_ids:
        return {
            "items": [],
            "total": 0,
            "limit": limit,
            "offset": offset,
        }

    conditions = ["a.actor_id = %s"]
    parameters: list[Any] = [actor_id]

    if action is not None:
        conditions.append("a.action = %s")
        parameters.append(action)

    if visible_team_ids is not None:
        conditions.append(
            """
            a.work_item_id IN (
                SELECT wi.id
                FROM work_items AS wi
                WHERE wi.team_id = ANY(%s::uuid[])
            )
            """
        )
        parameters.append(visible_team_ids)

    where_clause = "WHERE " + " AND ".join(conditions)

    count_query = f"""
        SELECT COUNT(*) AS total
        FROM work_item_activity AS a
        {where_clause};
    """

    list_query = f"""
        SELECT
            a.id,
            a.work_item_id,
            a.actor_id,
            a.action,
            a.details,
            a.created_at
        FROM work_item_activity AS a
        {where_clause}
        ORDER BY a.created_at DESC, a.id DESC
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
        log_database_failure(logger, "list_user_activity", exc)
        raise ActivityDatabaseError(
            "Unable to retrieve user activity right now."
        ) from None