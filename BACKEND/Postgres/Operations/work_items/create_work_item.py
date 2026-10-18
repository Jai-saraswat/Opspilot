"""Insert a work item into PostgreSQL."""

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
from BACKEND.Postgres.Operations.work_items.errors import (
    InvalidWorkItemRecordError,
    WorkItemDatabaseError,
    WorkItemRelatedRecordNotFoundError,
)

logger = logging.getLogger(__name__)


def create_work_item(
    *,
    title: str,
    description: str,
    type: str,
    team_id: UUID,
    created_by: UUID,
    priority: str = "medium",
    assignee_id: UUID | None = None,
    connection: psycopg.Connection | None = None,
) -> dict[str, Any]:
    """Insert a work item and return the created record.

    The service must verify team access and assignee membership before
    calling this function.
    """
    query = """
        INSERT INTO work_items (
            title,
            description,
            type,
            priority,
            team_id,
            created_by,
            assignee_id
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        RETURNING
            id,
            title,
            description,
            type,
            status,
            priority,
            team_id,
            created_by,
            assignee_id,
            created_at,
            updated_at,
            completed_at;
    """

    try:
        with connection_scope(connection) as conn:
            with conn.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    query,
                    (
                        title,
                        description,
                        type,
                        priority,
                        team_id,
                        created_by,
                        assignee_id,
                    ),
                )
                row = cursor.fetchone()

                if row is None:
                    raise WorkItemDatabaseError(
                        "The work item could not be created."
                    )

                return dict(row)

    except pg_errors.ForeignKeyViolation as exc:
        constraint = exc.diag.constraint_name

        if constraint == "work_items_team_id_fkey":
            raise WorkItemRelatedRecordNotFoundError(
                "The specified team does not exist."
            ) from None

        if constraint == "work_items_created_by_fkey":
            raise WorkItemRelatedRecordNotFoundError(
                "The specified creator does not exist."
            ) from None

        if constraint == "work_items_assignee_id_fkey":
            raise WorkItemRelatedRecordNotFoundError(
                "The specified assignee does not exist."
            ) from None

        log_database_failure(logger, "create_work_item", exc)
        raise WorkItemDatabaseError(
            "A related record prevented work-item creation."
        ) from None

    except pg_errors.CheckViolation as exc:
        log_database_failure(logger, "create_work_item", exc)
        raise InvalidWorkItemRecordError(
            "One or more work-item fields are invalid."
        ) from None

    except (psycopg.Error, RuntimeError) as exc:
        log_database_failure(logger, "create_work_item", exc)
        raise WorkItemDatabaseError(
            "Unable to create the work item right now."
        ) from None