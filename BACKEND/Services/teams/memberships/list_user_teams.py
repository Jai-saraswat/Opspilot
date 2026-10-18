"""List the teams that a user belongs to."""

from __future__ import annotations

import logging
from uuid import UUID

from BACKEND.Postgres.Operations.memberships.list_user_teams import (
    list_user_teams as list_user_teams_op,
)
from BACKEND.Postgres.Operations.memberships.errors import MembershipDatabaseError
from BACKEND.Services.teams._common import active_actor, fail, parse_uuid, success

logger = logging.getLogger(__name__)

DESCRIPTION = "List teams visible to a user for frontend team selection."


def list_user_teams(
    *,
    actor_user_id: UUID | str,
    user_id: UUID | str | None = None,
    limit: int = 50,
    offset: int = 0,
    search: str | None = None,
):
    actor_id = active_actor(actor_user_id)

    if actor_id is None:
        return fail(
            name="list_user_teams",
            description=DESCRIPTION,
            code="UNAUTHENTICATED",
            message="An active authenticated account is required.",
            status=401,
        )

    try:
        target_user_id = actor_id if user_id is None else parse_uuid(user_id)
    except (TypeError, ValueError, AttributeError):
        return fail(
            name="list_user_teams",
            description=DESCRIPTION,
            code="INVALID_USER_ID",
            message="A valid user identifier is required.",
            status=400,
        )

    # Users can query their own teams. Looking up another user's teams
    # requires an explicit administrative permission.
    if target_user_id != actor_id:
        from BACKEND.Services.teams._common import has_permission

        if not has_permission(actor_id, "teams:members:read:any", "teams:manage:any"):
            return fail(
                name="list_user_teams",
                description=DESCRIPTION,
                code="FORBIDDEN",
                message="You cannot list another user's teams.",
                status=403,
            )

    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 100:
        return fail(
            name="list_user_teams",
            description=DESCRIPTION,
            code="INVALID_LIMIT",
            message="Limit must be between 1 and 100.",
            status=400,
        )

    if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
        return fail(
            name="list_user_teams",
            description=DESCRIPTION,
            code="INVALID_OFFSET",
            message="Offset must be zero or greater.",
            status=400,
        )

    if search is not None and not isinstance(search, str):
        return fail(
            name="list_user_teams",
            description=DESCRIPTION,
            code="INVALID_SEARCH",
            message="Search must be text or null.",
            status=400,
        )

    try:
        result = list_user_teams_op(
            user_id=target_user_id,
            limit=limit,
            offset=offset,
            search=search,
        )

        items = []
        for row in result["items"]:
            item = dict(row)

            for key in ("id", "created_by"):
                if item.get(key) is not None:
                    item[key] = str(item[key])

            for key in ("created_at", "updated_at", "membership_joined_at"):
                if item.get(key) is not None:
                    item[key] = item[key].isoformat()

            items.append(item)

        return success(
            name="list_user_teams",
            description=DESCRIPTION,
            data={
                "items": items,
                "total": result["total"],
                "limit": result["limit"],
                "offset": result["offset"],
            },
            inputs={
                "user_id": str(target_user_id),
                "limit": limit,
                "offset": offset,
                "search": search,
            },
        )

    except MembershipDatabaseError:
        logger.exception("User team listing failed.")
        return fail(
            name="list_user_teams",
            description=DESCRIPTION,
            code="USER_TEAMS_LIST_FAILED",
            message="Unable to retrieve the user's teams right now.",
            status=500,
        )