"""Insert an immutable work-item activity record."""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

import psycopg
from psycopg import errors as pg_errors
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from BACKEND.Postgres.Operations._db import (
    connection_scope,
    log_database_failure,
)
from BACKEND.Postgres.Operations.activity.errors import (
    ActivityDatabaseError,
    ActivityRelatedRecordNotFoundError,
    InvalidActivityRecordError,
)

logger = logging.getLogger(__name__)


def create_activity(
    *,
    work_item_id: UUID,
    action: str,
    actor_id: UUID | None = None,
    details: dict[str, Any] | None = None,
    connection: psycopg.Connection | None = None,
) -> dict[str, Any]:
    """Create an activity record and return its stored fields.

    When connection is supplied, the caller owns the transaction.
    This permits the activity record to commit or roll back together
    with the work-item mutation it describes.

    This Operation performs no authorization or workflow checks.
    """
    query = """
        INSERT INTO work_item_activity (
            work_item_id,
            actor_id,
            action,
            details
        )
        VALUES (%s, %s, %s, %s)
        RETURNING
            id,
            work_item_id,
            actor_id,
            action,
            details,
            created_at;
    """

    activity_details = {} if details is None else details

    try:
        with connection_scope(connection) as conn:
            with conn.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    query,
                    (
                        work_item_id,
                        actor_id,
                        action,
                        Jsonb(activity_details),
                    ),
                )
                row = cursor.fetchone()

                if row is None:
                    raise ActivityDatabaseError(
                        "The activity record could not be created."
                    )

                return dict(row)

    except pg_errors.ForeignKeyViolation as exc:
        constraint = exc.diag.constraint_name

        if constraint == "work_item_activity_work_item_id_fkey":
            raise ActivityRelatedRecordNotFoundError(
                "The referenced work item does not exist."
            ) from None

        if constraint == "work_item_activity_actor_id_fkey":
            raise ActivityRelatedRecordNotFoundError(
                "The referenced actor does not exist."
            ) from None

        log_database_failure(logger, "create_activity", exc)
        raise ActivityDatabaseError(
            "Unable to create the activity record."
        ) from None

    except pg_errors.CheckViolation as exc:
        log_database_failure(logger, "create_activity", exc)
        raise InvalidActivityRecordError(
            "The activity action is invalid."
        ) from None

    except (psycopg.Error, RuntimeError) as exc:
        log_database_failure(logger, "create_activity", exc)
        raise ActivityDatabaseError(
            "Unable to create the activity record right now."
        ) from None