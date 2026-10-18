"""Retrieve a team by exact name after checking access."""

from __future__ import annotations

import logging
from uuid import UUID

from BACKEND.Postgres.Operations.teams.get_team_by_name import (
    get_team_by_name as get_team_by_name_op,
)
from BACKEND.Postgres.Operations.teams.errors import TeamDatabaseError

from ._common import (
    active_actor,
    can_view_team,
    fail,
    public_team,
    success,
)

logger = logging.getLogger(__name__)

DESCRIPTION = "Find a team by exact name with resource-level access checks."


def get_team_by_name(*, actor_user_id: UUID | str, name: str):
    actor_id = active_actor(actor_user_id)

    if actor_id is None:
        return fail(
            name="get_team_by_name",
            description=DESCRIPTION,
            code="UNAUTHENTICATED",
            message="An active authenticated account is required.",
            status=401,
        )

    if not isinstance(name, str) or not name.strip() or len(name.strip()) > 100:
        return fail(
            name="get_team_by_name",
            description=DESCRIPTION,
            code="INVALID_TEAM_NAME",
            message="A valid team name is required.",
            status=400,
        )

    try:
        team = get_team_by_name_op(name.strip())

        if team is None:
            return fail(
                name="get_team_by_name",
                description=DESCRIPTION,
                code="TEAM_NOT_FOUND",
                message="The team was not found.",
                status=404,
                inputs={"name": name.strip()},
            )

        team_id = team["id"]
        if not can_view_team(actor_id, team_id):
            return fail(
                name="get_team_by_name",
                description=DESCRIPTION,
                code="FORBIDDEN",
                message="You do not have access to this team.",
                status=403,
                inputs={"name": name.strip()},
            )

        return success(
            name="get_team_by_name",
            description=DESCRIPTION,
            data={"team": public_team(team)},
            inputs={"name": name.strip()},
        )

    except TeamDatabaseError:
        logger.exception("Team lookup by name failed.")
        return fail(
            name="get_team_by_name",
            description=DESCRIPTION,
            code="TEAM_LOOKUP_FAILED",
            message="Unable to retrieve the team right now.",
            status=500,
        )