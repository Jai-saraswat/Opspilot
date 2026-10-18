"""Retrieve a team after checking resource-level access."""

from __future__ import annotations

import logging
from uuid import UUID

from BACKEND.Postgres.Operations.teams.get_team_by_id import (
    get_team_by_id as get_team_op,
)
from BACKEND.Postgres.Operations.teams.errors import TeamDatabaseError

from ._common import (
    active_actor,
    can_view_team,
    fail,
    parse_uuid,
    public_team,
    success,
)

logger = logging.getLogger(__name__)

DESCRIPTION = "Retrieve team details after resource-level access checks."


def get_team_by_id(*, actor_user_id: UUID | str, team_id: UUID | str):
    try:
        actor_id = active_actor(actor_user_id)
        target_id = parse_uuid(team_id)
    except (TypeError, ValueError, AttributeError):
        return fail(
            name="get_team_by_id",
            description=DESCRIPTION,
            code="INVALID_TEAM_ID",
            message="A valid team identifier is required.",
            status=400,
        )

    if actor_id is None:
        return fail(
            name="get_team_by_id",
            description=DESCRIPTION,
            code="UNAUTHENTICATED",
            message="An active authenticated account is required.",
            status=401,
        )

    try:
        team = get_team_op(target_id)

        if team is None:
            return fail(
                name="get_team_by_id",
                description=DESCRIPTION,
                code="TEAM_NOT_FOUND",
                message="The team was not found.",
                status=404,
                inputs={"team_id": str(target_id)},
            )

        if not can_view_team(actor_id, target_id):
            return fail(
                name="get_team_by_id",
                description=DESCRIPTION,
                code="FORBIDDEN",
                message="You do not have access to this team.",
                status=403,
                inputs={"team_id": str(target_id)},
            )

        return success(
            name="get_team_by_id",
            description=DESCRIPTION,
            data={"team": public_team(team)},
            inputs={"team_id": str(target_id)},
        )

    except TeamDatabaseError:
        logger.exception("Team retrieval failed.")
        return fail(
            name="get_team_by_id",
            description=DESCRIPTION,
            code="TEAM_LOOKUP_FAILED",
            message="Unable to retrieve the team right now.",
            status=500,
        )