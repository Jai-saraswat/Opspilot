"""List members of a team with pagination and search."""

from __future__ import annotations

import logging
from uuid import UUID

from BACKEND.Postgres.Operations.teams.get_team_by_id import (
    get_team_by_id as get_team_op,
)
from BACKEND.Postgres.Operations.memberships.list_team_members import (
    list_team_members as list_members_op,
)
from BACKEND.Postgres.Operations.memberships.errors import MembershipDatabaseError
from BACKEND.Services.teams._common import active_actor, fail, parse_uuid, success

from ._common import can_view_members, validate_pagination

logger = logging.getLogger(__name__)

DESCRIPTION = "List searchable team members for the team management screen."


def list_team_members(
    *,
    actor_user_id: UUID | str,
    team_id: UUID | str,
    limit: int = 50,
    offset: int = 0,
    role: str | None = None,
    search: str | None = None,
):
    try:
        actor_id = active_actor(actor_user_id)
        target_team_id = parse_uuid(team_id)
    except (TypeError, ValueError, AttributeError):
        return fail(
            name="list_team_members",
            description=DESCRIPTION,
            code="INVALID_TEAM_ID",
            message="A valid team identifier is required.",
            status=400,
        )

    if actor_id is None:
        return fail(
            name="list_team_members",
            description=DESCRIPTION,
            code="UNAUTHENTICATED",
            message="An active authenticated account is required.",
            status=401,
        )

    pagination_error = validate_pagination(limit, offset)
    if pagination_error:
        return fail(
            name="list_team_members",
            description=DESCRIPTION,
            code="INVALID_PAGINATION",
            message=pagination_error,
            status=400,
        )

    if role is not None and role not in {"lead", "member", "approver"}:
        return fail(
            name="list_team_members",
            description=DESCRIPTION,
            code="INVALID_MEMBERSHIP_ROLE",
            message="Role must be lead, member or approver.",
            status=400,
        )

    if search is not None and not isinstance(search, str):
        return fail(
            name="list_team_members",
            description=DESCRIPTION,
            code="INVALID_SEARCH",
            message="Search must be text or null.",
            status=400,
        )

    try:
        if get_team_op(target_team_id) is None:
            return fail(
                name="list_team_members",
                description=DESCRIPTION,
                code="TEAM_NOT_FOUND",
                message="The team was not found.",
                status=404,
            )

        if not can_view_members(actor_id, target_team_id):
            return fail(
                name="list_team_members",
                description=DESCRIPTION,
                code="FORBIDDEN",
                message="You do not have access to this team's memberships.",
                status=403,
            )

        result = list_members_op(
            team_id=target_team_id,
            limit=limit,
            offset=offset,
            role=role,
            search=search,
        )

        return success(
            name="list_team_members",
            description=DESCRIPTION,
            data=result,
            inputs={
                "team_id": str(target_team_id),
                "limit": limit,
                "offset": offset,
                "role": role,
                "search": search,
            },
        )

    except MembershipDatabaseError:
        logger.exception("Team member listing failed.")
        return fail(
            name="list_team_members",
            description=DESCRIPTION,
            code="MEMBERSHIP_LIST_FAILED",
            message="Unable to retrieve team members right now.",
            status=500,
        )