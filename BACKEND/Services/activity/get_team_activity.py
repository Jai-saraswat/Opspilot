"""Retrieve a team's paginated activity feed."""

from __future__ import annotations

from uuid import UUID

from BACKEND.Postgres.Operations.activity.errors import ActivityDatabaseError
from BACKEND.Postgres.Operations.activity.list_team_activity import (
    list_team_activity,
)
from BACKEND.Postgres.Operations.teams.errors import TeamDatabaseError
from BACKEND.Postgres.Operations.teams.get_team_by_id import get_team_by_id
from BACKEND.Services.activity._common import (
    active_actor,
    fail,
    parse_identifier,
    public_activities,
    success,
    valid_pagination,
)
from BACKEND.Services.work_management._common import can_view_team


def get_team_activity(
    *,
    actor_user_id: UUID | str,
    team_id: UUID | str,
    limit: int = 50,
    offset: int = 0,
    action: str | None = None,
):
    name = "get_team_activity"
    inputs = {
        "team_id": str(team_id),
        "limit": limit,
        "offset": offset,
        "action": action,
    }

    actor_id = active_actor(actor_user_id)

    if actor_id is None:
        return fail(
            name=name,
            description="List activity for a team.",
            code="UNAUTHENTICATED",
            message="An active user account is required.",
            status=401,
            inputs=inputs,
        )

    try:
        resolved_team_id = parse_identifier(team_id)
    except (ValueError, TypeError, AttributeError):
        return fail(
            name=name,
            description="List activity for a team.",
            code="INVALID_TEAM_ID",
            message="The team identifier is invalid.",
            status=400,
            inputs=inputs,
        )

    if not valid_pagination(limit, offset):
        return fail(
            name=name,
            description="List activity for a team.",
            code="INVALID_PAGINATION",
            message="Limit must be 1–100 and offset must be non-negative.",
            status=400,
            inputs=inputs,
        )

    if action is not None and (
        not isinstance(action, str)
        or not action.strip()
        or len(action.strip()) > 50
    ):
        return fail(
            name=name,
            description="List activity for a team.",
            code="INVALID_ACTION",
            message="Action filter must contain 1–50 characters.",
            status=400,
            inputs=inputs,
        )

    try:
        team = get_team_by_id(resolved_team_id)

        if team is None:
            return fail(
                name=name,
                description="List activity for a team.",
                code="TEAM_NOT_FOUND",
                message="The team does not exist.",
                status=404,
                inputs=inputs,
            )

        if not can_view_team(actor_id, resolved_team_id):
            return fail(
                name=name,
                description="List activity for a team.",
                code="FORBIDDEN",
                message="You cannot access this team's activity.",
                status=403,
                inputs=inputs,
            )

        result = list_team_activity(
            resolved_team_id,
            limit=limit,
            offset=offset,
            action=action.strip() if action else None,
        )

        return success(
            name=name,
            description="Team activity retrieved.",
            data={
                "items": public_activities(result["items"]),
                "total": result["total"],
                "limit": result["limit"],
                "offset": result["offset"],
            },
            inputs=inputs,
        )

    except TeamDatabaseError:
        return fail(
            name=name,
            description="List activity for a team.",
            code="DATABASE_ERROR",
            message="The team could not be retrieved right now.",
            status=500,
            inputs=inputs,
        )
    except ActivityDatabaseError:
        return fail(
            name=name,
            description="List activity for a team.",
            code="DATABASE_ERROR",
            message="Team activity could not be retrieved right now.",
            status=500,
            inputs=inputs,
        )
    except ValueError as exc:
        return fail(
            name=name,
            description="List activity for a team.",
            code="INVALID_FILTER",
            message=str(exc),
            status=400,
            inputs=inputs,
        )