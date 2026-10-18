"""Assign an eligible approver to a pending approval request."""

from __future__ import annotations

from uuid import UUID

from BACKEND.Postgres.Operations.activity.errors import (
    ActivityDatabaseError,
    ActivityRelatedRecordNotFoundError,
    InvalidActivityRecordError,
)
from BACKEND.Postgres.Operations.approvals.assign_approval_approver import (
    assign_approval_approver as assign_approver_operation,
)
from BACKEND.Postgres.Operations.approvals.errors import (
    ApprovalDatabaseError,
    ApprovalRelatedRecordNotFoundError,
)
from BACKEND.Postgres.Operations.approvals.get_approval_request_by_id import (
    get_approval_request_by_id,
)
from BACKEND.Postgres.Operations.work_items.errors import WorkItemDatabaseError
from BACKEND.Postgres.Operations.work_items.get_work_item_by_id import (
    get_work_item_by_id,
)
from BACKEND.Services.approvals._common import (
    active_actor,
    eligible_approver,
    fail,
    may_assign_approver,
    parse_identifier,
    public_approval,
    record_work_item_activity,
    success,
)
from BACKEND.Services.idempotency import execute_idempotently


class _AssignConflict(Exception):
    """Roll back if the approval request stops being pending."""


def assign_approval_approver(
    *,
    actor_user_id: UUID | str,
    approval_request_id: UUID | str,
    approver_id: UUID | str | None,
    idempotency_key: str | None = None,
):
    name = "assign_approval_approver"
    inputs = {"approval_request_id": str(approval_request_id)}

    actor_id = active_actor(actor_user_id)
    if actor_id is None:
        return fail(
            name=name,
            description="Assign an approval approver.",
            code="UNAUTHENTICATED",
            message="An active user account is required.",
            status=401,
            inputs=inputs,
        )

    try:
        request_id = parse_identifier(approval_request_id)
        target_id = (
            parse_identifier(approver_id)
            if approver_id is not None
            else None
        )
    except (ValueError, TypeError, AttributeError):
        return fail(
            name=name,
            description="Assign an approval approver.",
            code="INVALID_IDENTIFIER",
            message="The approval or approver identifier is invalid.",
            status=400,
            inputs=inputs,
        )

    try:
        def _assign(connection):
            request = get_approval_request_by_id(
                request_id,
                connection=connection,
            )

            if request is None:
                return fail(
                    name=name,
                    description="Assign an approval approver.",
                    code="APPROVAL_NOT_FOUND",
                    message="The approval request does not exist.",
                    status=404,
                    inputs=inputs,
                )

            item = get_work_item_by_id(
                request["work_item_id"],
                connection=connection,
            )

            if item is None:
                return fail(
                    name=name,
                    description="Assign an approval approver.",
                    code="WORK_ITEM_NOT_FOUND",
                    message="The associated work item does not exist.",
                    status=404,
                    inputs=inputs,
                )

            team_id = item["team_id"]

            if not may_assign_approver(actor_id, team_id):
                return fail(
                    name=name,
                    description="Assign an approval approver.",
                    code="FORBIDDEN",
                    message=(
                        "Only team leads or explicitly authorized managers "
                        "may assign approvers."
                    ),
                    status=403,
                    inputs=inputs,
                )

            if request["status"] != "pending":
                return fail(
                    name=name,
                    description="Assign an approval approver.",
                    code="REQUEST_NOT_PENDING",
                    message=(
                        "Only pending approval requests can be reassigned."
                    ),
                    status=409,
                    inputs=inputs,
                )

            if target_id is not None:
                if target_id == request["requested_by"]:
                    return fail(
                        name=name,
                        description="Assign an approval approver.",
                        code="SELF_APPROVAL_NOT_ALLOWED",
                        message="The requester cannot be their own approver.",
                        status=400,
                        inputs=inputs,
                    )

                if not eligible_approver(team_id, target_id):
                    return fail(
                        name=name,
                        description="Assign an approval approver.",
                        code="INVALID_APPROVER",
                        message=(
                            "The selected approver must be an active team "
                            "lead or member with the approver role."
                        ),
                        status=400,
                        inputs=inputs,
                    )

            old_approver_id = request.get("approver_id")

            if old_approver_id == target_id:
                return success(
                    name=name,
                    description="The requested approver is already assigned.",
                    data={"approval_request": public_approval(request)},
                    inputs=inputs,
                )

            assigned = assign_approver_operation(
                request_id,
                target_id,
                connection=connection,
            )

            if assigned is None:
                raise _AssignConflict()

            record_work_item_activity(
                connection=connection,
                work_item_id=item["id"],
                actor_id=actor_id,
                action="approval_approver_assigned",
                details={
                    "approval_request_id": str(request_id),
                    "old_approver_id": (
                        str(old_approver_id)
                        if old_approver_id
                        else None
                    ),
                    "new_approver_id": (
                        str(target_id) if target_id else None
                    ),
                },
            )

            return success(
                name=name,
                description="Approval approver assigned.",
                data={"approval_request": public_approval(assigned)},
                inputs=inputs,
            )

        return execute_idempotently(
            user_id=actor_id,
            idempotency_key=idempotency_key,
            operation_name=name,
            category="approvals",
            subcategory="approval_workflow",
            description="Assign an approval approver.",
            payload={
                "approval_request_id": str(request_id),
                "approver_id": str(target_id) if target_id else None,
            },
            operation=_assign,
        )

    except _AssignConflict:
        return fail(
            name=name,
            description="Assign an approval approver.",
            code="APPROVAL_STATE_CHANGED",
            message=(
                "The approval request was no longer pending. "
                "No assignment was committed."
            ),
            status=409,
            inputs=inputs,
        )
    except ApprovalRelatedRecordNotFoundError:
        return fail(
            name=name,
            description="Assign an approval approver.",
            code="RELATED_RECORD_NOT_FOUND",
            message=(
                "The approval request or selected approver could not be found."
            ),
            status=404,
            inputs=inputs,
        )
    except ActivityRelatedRecordNotFoundError:
        return fail(
            name=name,
            description="Assign an approval approver.",
            code="RELATED_RECORD_NOT_FOUND",
            message="The activity actor or work item could not be found.",
            status=404,
            inputs=inputs,
        )
    except InvalidActivityRecordError:
        return fail(
            name=name,
            description="Assign an approval approver.",
            code="ACTIVITY_WRITE_FAILED",
            message=(
                "The assignment was not committed because its activity "
                "event could not be recorded."
            ),
            status=500,
            inputs=inputs,
        )
    except (
        ApprovalDatabaseError,
        WorkItemDatabaseError,
        ActivityDatabaseError,
    ):
        return fail(
            name=name,
            description="Assign an approval approver.",
            code="DATABASE_ERROR",
            message="The approver could not be assigned right now.",
            status=500,
            inputs=inputs,
        )