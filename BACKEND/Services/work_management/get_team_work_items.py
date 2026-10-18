"""List work items for an authorized team."""

from __future__ import annotations

from uuid import UUID

from BACKEND.Services.work_management.list_work_items import (
    list_work_items as list_work_items_service,
)


def get_team_work_items(
    *,
    actor_user_id: UUID | str,
    team_id: UUID | str,
    limit: int = 50,
    offset: int = 0,
    assignee_id: UUID | str | None = None,
    unassigned_only: bool = False,
    status: str | None = None,
    priority: str | None = None,
    type: str | None = None,
    search: str | None = None,
):
    return list_work_items_service(
        actor_user_id=actor_user_id,
        team_id=team_id,
        limit=limit,
        offset=offset,
        assignee_id=assignee_id,
        unassigned_only=unassigned_only,
        status=status,
        priority=priority,
        type=type,
        search=search,
    )