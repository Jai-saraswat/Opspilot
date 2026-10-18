"""Retrieve a specific user's membership in a team."""

from __future__ import annotations

import logging
from uuid import UUID

from BACKEND.Postgres.Operations.teams.get_team_by_id import (
    get_team_by_id as get_team_op,
)
from BACKEND.Postgres.Operations.memberships.get_membership import (
    get_membership as get_membership_op,
)
from BACKEND.Postgres.Operations.memberships.errors import MembershipDatabaseError
from BACKEND.Services.teams._common import active_actor, fail, parse_uuid, success

from ._common import can_view_members, public_membership

logger = logging.getLogger(__name__)

DESCRIPTION = "Retrieve a user's membership after checking team access."


def get_membership(
    *,
    actor_user_id: UUID | str,
    team_id: UUID | str,
    user_id: UUID | str,
):
    try:
        actor_id = active_actor(actor_user_id)
        target_team_id = parse_uuid(team_id)
        target_user_id = parse_uuid(user_id)
    except (TypeError, ValueError, AttributeError):
        return fail(
            name="get_membership",
            description=DESCRIPTION,
            code="INVALID_IDENTIFIER",
            message="Valid team and user identifiers are required.",
            status=400,
        )

    if actor_id is None:
        return fail(
            name="get_membership",
            description=DESCRIPTION,
            code="UNAUTHENTICATED",
            message="An active authenticated account is required.",
            status=401,
        )

    try:
        if get_team_op(target_team_id) is None:
            return fail(
                name="get_membership",
                description=DESCRIPTION,
                code="TEAM_NOT_FOUND",
                message="The team was not found.",
                status=404,
            )

        if not can_view_members(actor_id, target_team_id):
            return fail(
                name="get_membership",
                description=DESCRIPTION,
                code="FORBIDDEN",
                message="You do not have access to this team's memberships.",
                status=403,
            )

        membership = get_membership_op(
            team_id=target_team_id,
            user_id=target_user_id,
        )

        if membership is None:
            return fail(
                name="get_membership",
                description=DESCRIPTION,
                code="MEMBERSHIP_NOT_FOUND",
                message="The user is not a member of this team.",
                status=404,
            )

        return success(
            name="get_membership",
            description=DESCRIPTION,
            data={"membership": public_membership(membership)},
            inputs={
                "team_id": str(target_team_id),
                "user_id": str(target_user_id),
            },
        )

    except MembershipDatabaseError:
        logger.exception("Membership retrieval failed.")
        return fail(
            name="get_membership",
            description=DESCRIPTION,
            code="MEMBERSHIP_LOOKUP_FAILED",
            message="Unable to retrieve the membership right now.",
            status=500,
        )