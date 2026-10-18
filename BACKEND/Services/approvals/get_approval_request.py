"""Retrieve one approval request with resource-level access checks."""

from __future__ import annotations

from uuid import UUID

from BACKEND.Postgres.Operations.approvals.errors import ApprovalDatabaseError
from BACKEND.Postgres.Operations.approvals.get_approval_request_by_id import (
    get_approval_request_by_id,
)
from BACKEND.Postgres.Operations.work_items.errors import WorkItemDatabaseError
from BACKEND.Postgres.Operations.work_items.get_work_item_by_id import (
    get_work_item_by_id,
)
from BACKEND.Services.approvals._common import (
    active_actor,
    fail,
    may_view_approval,
    parse_identifier,
    public_approval,
    success,
)


def get_approval_request(
    *,
    actor_user_id: UUID | str,
    approval_request_id: UUID | str,
):
    name = "get_approval_request"
    inputs = {"approval_request_id": str(approval_request_id)}

    actor_id = active_actor(actor_user_id)
    if actor_id is None:
        return fail(
            name=name,
            description="Retrieve an approval request.",
            code="UNAUTHENTICATED",
            message="An active user account is required.",
            status=401,
            inputs=inputs,
        )

    try:
        request_id = parse_identifier(approval_request_id)
    except (ValueError, TypeError, AttributeError):
        return fail(
            name=name,
            description="Retrieve an approval request.",
            code="INVALID_APPROVAL_ID",
            message="The approval-request identifier is invalid.",
            status=400,
            inputs=inputs,
        )

    try:
        request = get_approval_request_by_id(request_id)

        if request is None:
            return fail(
                name=name,
                description="Retrieve an approval request.",
                code="APPROVAL_NOT_FOUND",
                message="The approval request does not exist.",
                status=404,
                inputs=inputs,
            )

        item = get_work_item_by_id(request["work_item_id"])

        if item is None:
            return fail(
                name=name,
                description="Retrieve an approval request.",
                code="WORK_ITEM_NOT_FOUND",
                message="The associated work item does not exist.",
                status=404,
                inputs=inputs,
            )

        if not may_view_approval(actor_id, request, item):
            return fail(
                name=name,
                description="Retrieve an approval request.",
                code="FORBIDDEN",
                message="You cannot access this approval request.",
                status=403,
                inputs=inputs,
            )

        return success(
            name=name,
            description="Approval request retrieved.",
            data={"approval_request": public_approval(request)},
            inputs=inputs,
        )

    except (ApprovalDatabaseError, WorkItemDatabaseError):
        return fail(
            name=name,
            description="Retrieve an approval request.",
            code="DATABASE_ERROR",
            message="The approval request could not be retrieved right now.",
            status=500,
            inputs=inputs,
        )