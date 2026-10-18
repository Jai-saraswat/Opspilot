"""List teams visible to the actor with search and pagination."""

from __future__ import annotations

import logging
from uuid import UUID

from BACKEND.Postgres.Operations.teams.list_teams import (
    list_teams as list_teams_op,
)
from BACKEND.Postgres.Operations.memberships.list_user_teams import (
    list_user_teams,
)
from BACKEND.Postgres.Operations.teams.errors import TeamDatabaseError
from BACKEND.Postgres.Operations.memberships.errors import MembershipDatabaseError

from ._common import (
    active_actor,
    fail,
    has_permission,
    public_team,
    success,
)

logger = logging.getLogger(__name__)

DESCRIPTION = "List searchable teams for administration and team selection."


def list_teams(
    *,
    actor_user_id: UUID | str,
    limit: int = 50,
    offset: int = 0,
    search: str | None = None,
):
    actor_id = active_actor(actor_user_id)

    if actor_id is None:
        return fail(
            name="list_teams",
            description=DESCRIPTION,
            code="UNAUTHENTICATED",
            message="An active authenticated account is required.",
            status=401,
        )

    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 100:
        return fail(
            name="list_teams",
            description=DESCRIPTION,
            code="INVALID_LIMIT",
            message="Limit must be between 1 and 100.",
            status=400,
        )

    if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
        return fail(
            name="list_teams",
            description=DESCRIPTION,
            code="INVALID_OFFSET",
            message="Offset must be zero or greater.",
            status=400,
        )

    if search is not None and not isinstance(search, str):
        return fail(
            name="list_teams",
            description=DESCRIPTION,
            code="INVALID_SEARCH",
            message="Search must be text or null.",
            status=400,
        )

    try:
        if has_permission(
            actor_id,
            "teams:list:any",
            "teams:manage:any",
        ):
            result = list_teams_op(
                limit=limit,
                offset=offset,
                search=search,
            )
            items = [public_team(team) for team in result["items"]]
        else:
            # A regular user sees only teams to which they belong.
            result = list_user_teams(
                user_id=actor_id,
                limit=limit,
                offset=offset,
                search=search,
            )
            items = []
            for row in result["items"]:
                team = {
                    key: row.get(key)
                    for key in (
                        "id",
                        "name",
                        "description",
                        "created_by",
                        "created_at",
                        "updated_at",
                    )
                }
                item = public_team(team)
                item["membership_role"] = row.get("membership_role")
                item["membership_joined_at"] = (
                    row["membership_joined_at"].isoformat()
                    if row.get("membership_joined_at") is not None
                    else None
                )
                items.append(item)

        return success(
            name="list_teams",
            description=DESCRIPTION,
            data={
                "items": items,
                "total": result["total"],
                "limit": result["limit"],
                "offset": result["offset"],
            },
            inputs={
                "limit": limit,
                "offset": offset,
                "search": search,
            },
        )

    except (TeamDatabaseError, MembershipDatabaseError):
        logger.exception("Team listing failed.")
        return fail(
            name="list_teams",
            description=DESCRIPTION,
            code="TEAM_LIST_FAILED",
            message="Unable to retrieve teams right now.",
            status=500,
        )