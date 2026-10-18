"""Compatibility wrapper for retrieving a user's activity feed."""

from __future__ import annotations

from typing import Any
from uuid import UUID

import psycopg

from BACKEND.Postgres.Operations.activity.list_user_activity import (
    list_user_activity,
)


def get_user_activity(
    actor_id: UUID,
    *,
    limit: int = 50,
    offset: int = 0,
    action: str | None = None,
    visible_team_ids: list[UUID] | None = None,
    connection: psycopg.Connection | None = None,
) -> dict[str, Any]:
    """Return the user's paginated activity feed."""
    return list_user_activity(
        actor_id,
        limit=limit,
        offset=offset,
        action=action,
        visible_team_ids=visible_team_ids,
        connection=connection,
    )