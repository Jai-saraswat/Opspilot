"""Retrieve the current actor's eligible pending approval queue."""

from __future__ import annotations

from uuid import UUID

from BACKEND.Postgres.Operations.approvals.errors import ApprovalDatabaseError
from BACKEND.Postgres.Operations.approvals.list_pending_approvals import (
    list_pending_approvals,
)
from BACKEND.Postgres.Operations.memberships.errors import MembershipDatabaseError
from BACKEND.Postgres.Operations.memberships.list_user_teams import (
    list_user_teams,
)
from BACKEND.Services.approvals._common import (
    active_actor,
    fail,
    parse_identifier,
    public_approvals,
    success,
    valid_pagination,
)


def _eligible_team_ids(user_id: UUID) -> list[UUID]:
    """Get all current teams where this actor may review approvals."""
    result_ids: list[UUID] = []
    offset = 0

    while True:
        page = list_user_teams(
            user_id=user_id,
            limit=100,
            offset=offset,
        )

        rows = page["items"]
        total = page["total"]

        for row in rows:
            if row.get("membership_role") in {"lead", "approver"}:
                result_ids.append(parse_identifier(row["id"]))

        offset += len(rows)

        if not rows or offset >= total:
            break

    return list(dict.fromkeys(result_ids))


def get_pending_approvals(
    *,
    actor_user_id: UUID | str,
    limit: int = 50,
    offset: int = 0,
):
    name = "get_pending_approvals"
    inputs = {"limit": limit, "offset": offset}

    actor_id = active_actor(actor_user_id)
    if actor_id is None:
        return fail(
            name=name,
            description="List pending approvals assigned to the current user.",
            code="UNAUTHENTICATED",
            message="An active user account is required.",
            status=401,
            inputs=inputs,
        )

    if not valid_pagination(limit, offset):
        return fail(
            name=name,
            description="List pending approvals assigned to the current user.",
            code="INVALID_PAGINATION",
            message="Limit must be 1–100 and offset must be non-negative.",
            status=400,
            inputs=inputs,
        )

    try:
        team_ids = _eligible_team_ids(actor_id)

        if not team_ids:
            return success(
                name=name,
                description="No eligible pending approvals were found.",
                data={
                    "items": [],
                    "total": 0,
                    "limit": limit,
                    "offset": offset,
                },
                inputs=inputs,
            )

        result = list_pending_approvals(
            approver_id=actor_id,
            team_ids=team_ids,
            limit=limit,
            offset=offset,
        )

        return success(
            name=name,
            description="Pending approvals retrieved.",
            data={
                "items": public_approvals(result["items"]),
                "total": result["total"],
                "limit": result["limit"],
                "offset": result["offset"],
            },
            inputs=inputs,
        )

    except MembershipDatabaseError:
        return fail(
            name=name,
            description="List pending approvals assigned to the current user.",
            code="DATABASE_ERROR",
            message="Team membership could not be retrieved right now.",
            status=500,
            inputs=inputs,
        )
    except ApprovalDatabaseError:
        return fail(
            name=name,
            description="List pending approvals assigned to the current user.",
            code="DATABASE_ERROR",
            message="Pending approvals could not be retrieved right now.",
            status=500,
            inputs=inputs,
        )
    except ValueError as exc:
        return fail(
            name=name,
            description="List pending approvals assigned to the current user.",
            code="INVALID_FILTER",
            message=str(exc),
            status=400,
            inputs=inputs,
        )