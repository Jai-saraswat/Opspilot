"""Retrieve a user's activity feed within the authorized scope."""

from __future__ import annotations

from uuid import UUID

from BACKEND.Postgres.Operations.activity.errors import ActivityDatabaseError
from BACKEND.Postgres.Operations.activity.list_user_activity import (
    list_user_activity,
)
from BACKEND.Postgres.Operations.memberships.errors import (
    MembershipDatabaseError,
)
from BACKEND.Postgres.Operations.memberships.list_user_teams import (
    list_user_teams,
)
from BACKEND.Postgres.Operations.users.get_user_by_id import get_user_by_id
from BACKEND.Services.activity._common import (
    active_actor,
    fail,
    parse_identifier,
    public_activities,
    success,
    valid_pagination,
)
from BACKEND.Services.work_management._common import has_permission


def _get_user_team_ids(user_id: UUID) -> list[UUID]:
    """Fetch all team IDs using bounded, database-side pagination."""
    team_ids: list[UUID] = []
    offset = 0
    page_size = 100

    while True:
        page = list_user_teams(
            user_id=user_id,
            limit=page_size,
            offset=offset,
        )

        rows = page["items"]
        total = page["total"]

        for row in rows:
            team_ids.append(parse_identifier(row["id"]))

        offset += len(rows)

        if not rows or offset >= total:
            break

    # Preserve order and eliminate any accidental duplicates.
    return list(dict.fromkeys(team_ids))


def get_user_activity(
    *,
    actor_user_id: UUID | str,
    user_id: UUID | str | None = None,
    limit: int = 50,
    offset: int = 0,
    action: str | None = None,
):
    name = "get_user_activity"
    inputs = {
        "user_id": str(user_id) if user_id is not None else "self",
        "limit": limit,
        "offset": offset,
        "action": action,
    }

    viewer_id = active_actor(actor_user_id)

    if viewer_id is None:
        return fail(
            name=name,
            description="List user activity.",
            code="UNAUTHENTICATED",
            message="An active user account is required.",
            status=401,
            inputs=inputs,
        )

    if not valid_pagination(limit, offset):
        return fail(
            name=name,
            description="List user activity.",
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
            description="List user activity.",
            code="INVALID_ACTION",
            message="Action filter must contain 1–50 characters.",
            status=400,
            inputs=inputs,
        )

    try:
        target_id = (
            parse_identifier(user_id)
            if user_id is not None
            else viewer_id
        )
    except (ValueError, TypeError, AttributeError):
        return fail(
            name=name,
            description="List user activity.",
            code="INVALID_USER_ID",
            message="The user identifier is invalid.",
            status=400,
            inputs=inputs,
        )

    try:
        target = get_user_by_id(target_id)

        if target is None or target.get("account_status") != "active":
            return fail(
                name=name,
                description="List user activity.",
                code="USER_NOT_FOUND",
                message="The requested active user was not found.",
                status=404,
                inputs=inputs,
            )

        if target_id == viewer_id:
            visible_team_ids = _get_user_team_ids(viewer_id)
        else:
            globally_authorized = has_permission(
                viewer_id,
                "work_items:read:any",
                "work_items:list:any",
                "work_items:manage:any",
            )

            if not globally_authorized:
                return fail(
                    name=name,
                    description="List user activity.",
                    code="FORBIDDEN",
                    message="You cannot inspect another user's activity.",
                    status=403,
                    inputs=inputs,
                )

            visible_team_ids = None

        result = list_user_activity(
            target_id,
            limit=limit,
            offset=offset,
            action=action.strip() if action else None,
            visible_team_ids=visible_team_ids,
        )

        return success(
            name=name,
            description="User activity retrieved.",
            data={
                "items": public_activities(result["items"]),
                "total": result["total"],
                "limit": result["limit"],
                "offset": result["offset"],
            },
            inputs=inputs,
        )

    except MembershipDatabaseError:
        return fail(
            name=name,
            description="List user activity.",
            code="DATABASE_ERROR",
            message="The user's team access could not be retrieved right now.",
            status=500,
            inputs=inputs,
        )
    except ActivityDatabaseError:
        return fail(
            name=name,
            description="List user activity.",
            code="DATABASE_ERROR",
            message="User activity could not be retrieved right now.",
            status=500,
            inputs=inputs,
        )
    except ValueError as exc:
        return fail(
            name=name,
            description="List user activity.",
            code="INVALID_FILTER",
            message=str(exc),
            status=400,
            inputs=inputs,
        )