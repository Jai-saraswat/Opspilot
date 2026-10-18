"""List approval requests submitted by a user."""

from __future__ import annotations

from uuid import UUID

from BACKEND.Postgres.Operations.approvals.errors import ApprovalDatabaseError
from BACKEND.Postgres.Operations.approvals.list_user_approval_requests import (
    list_user_approval_requests,
)
from BACKEND.Postgres.Operations.users.get_user_by_id import get_user_by_id
from BACKEND.Services.approvals._common import (
    active_actor,
    fail,
    has_permission,
    parse_identifier,
    public_approvals,
    success,
    valid_pagination,
)

VALID_STATUSES = {"pending", "approved", "rejected"}


def get_user_approval_requests(
    *,
    actor_user_id: UUID | str,
    requested_by: UUID | str | None = None,
    limit: int = 50,
    offset: int = 0,
    status: str | None = None,
):
    name = "list_user_approval_requests"
    inputs = {
        "requested_by": (
            str(requested_by) if requested_by is not None else "self"
        ),
        "limit": limit,
        "offset": offset,
        "status": status,
    }

    actor_id = active_actor(actor_user_id)
    if actor_id is None:
        return fail(
            name=name,
            description="List a user's approval requests.",
            code="UNAUTHENTICATED",
            message="An active user account is required.",
            status=401,
            inputs=inputs,
        )

    if not valid_pagination(limit, offset):
        return fail(
            name=name,
            description="List a user's approval requests.",
            code="INVALID_PAGINATION",
            message="Limit must be 1–100 and offset must be non-negative.",
            status=400,
            inputs=inputs,
        )

    if status is not None and status not in VALID_STATUSES:
        return fail(
            name=name,
            description="List a user's approval requests.",
            code="INVALID_STATUS",
            message="The approval status filter is invalid.",
            status=400,
            inputs=inputs,
        )

    try:
        target_id = (
            parse_identifier(requested_by)
            if requested_by is not None
            else actor_id
        )
    except (ValueError, TypeError, AttributeError):
        return fail(
            name=name,
            description="List a user's approval requests.",
            code="INVALID_USER_ID",
            message="The requester identifier is invalid.",
            status=400,
            inputs=inputs,
        )

    try:
        user = get_user_by_id(target_id)

        if user is None:
            return fail(
                name=name,
                description="List a user's approval requests.",
                code="USER_NOT_FOUND",
                message="The requested user does not exist.",
                status=404,
                inputs=inputs,
            )

        if target_id != actor_id and not has_permission(
            actor_id,
            "approvals:read:any",
            "work_items:read:any",
            "work_items:manage:any",
        ):
            return fail(
                name=name,
                description="List a user's approval requests.",
                code="FORBIDDEN",
                message="You cannot inspect another user's approval requests.",
                status=403,
                inputs=inputs,
            )

        result = list_user_approval_requests(
            target_id,
            limit=limit,
            offset=offset,
            status=status,
        )

        return success(
            name=name,
            description="User approval requests retrieved.",
            data={
                "items": public_approvals(result["items"]),
                "total": result["total"],
                "limit": result["limit"],
                "offset": result["offset"],
            },
            inputs=inputs,
        )

    except ApprovalDatabaseError:
        return fail(
            name=name,
            description="List a user's approval requests.",
            code="DATABASE_ERROR",
            message="Approval requests could not be retrieved right now.",
            status=500,
            inputs=inputs,
        )