"""Approve or reject an approval request and update the work item atomically."""

from __future__ import annotations

from uuid import UUID

from BACKEND.Postgres.Operations.activity.errors import (
    ActivityDatabaseError,
    ActivityRelatedRecordNotFoundError,
    InvalidActivityRecordError,
)
from BACKEND.Postgres.Operations.approvals.errors import (
    ApprovalDatabaseError,
    ApprovalRelatedRecordNotFoundError,
    InvalidApprovalRecordError,
)
from BACKEND.Postgres.Operations.approvals.get_approval_request_by_id import (
    get_approval_request_by_id,
)
from BACKEND.Postgres.Operations.approvals.record_approval_decision_if_pending import (
    record_approval_decision_if_pending,
)
from BACKEND.Postgres.Operations.work_items.errors import WorkItemDatabaseError
from BACKEND.Postgres.Operations.work_items.get_work_item_by_id import (
    get_work_item_by_id,
)
from BACKEND.Postgres.Operations.work_items.update_work_item_status import (
    update_work_item_status,
)
from BACKEND.Services.approvals._common import (
    active_actor,
    eligible_approver,
    fail,
    parse_identifier,
    public_approval,
    record_work_item_activity,
    success,
)
from BACKEND.Services.idempotency import execute_idempotently


class _ReviewConflict(Exception):
    """Roll back partial decision writes."""


def review_approval_request(
    *,
    actor_user_id: UUID | str,
    approval_request_id: UUID | str,
    decision: str,
    decision_reason: str | None = None,
    idempotency_key: str | None = None,
):
    """Review a pending request.

    approved -> request approved and work item resolved.
    rejected -> request rejected and work item returned to in_progress.
    """
    name = "review_approval_request"
    inputs = {
        "approval_request_id": str(approval_request_id),
        "decision": decision,
    }

    actor_id = active_actor(actor_user_id)
    if actor_id is None:
        return fail(
            name=name,
            description="Review an approval request.",
            code="UNAUTHENTICATED",
            message="An active user account is required.",
            status=401,
            inputs=inputs,
        )

    if decision not in {"approved", "rejected"}:
        return fail(
            name=name,
            description="Review an approval request.",
            code="INVALID_DECISION",
            message="Decision must be 'approved' or 'rejected'.",
            status=400,
            inputs=inputs,
        )

    if decision_reason is not None:
        if not isinstance(decision_reason, str):
            return fail(
                name=name,
                description="Review an approval request.",
                code="INVALID_DECISION_REASON",
                message="The decision reason must be text.",
                status=400,
                inputs=inputs,
            )

        decision_reason = decision_reason.strip() or None

    try:
        request_id = parse_identifier(approval_request_id)
    except (ValueError, TypeError, AttributeError):
        return fail(
            name=name,
            description="Review an approval request.",
            code="INVALID_APPROVAL_ID",
            message="The approval-request identifier is invalid.",
            status=400,
            inputs=inputs,
        )

    try:
        def _review(connection):
            request = get_approval_request_by_id(
                request_id,
                connection=connection,
            )

            if request is None:
                return fail(
                    name=name,
                    description="Review an approval request.",
                    code="APPROVAL_NOT_FOUND",
                    message="The approval request does not exist.",
                    status=404,
                    inputs=inputs,
                )

            if request["status"] != "pending":
                return fail(
                    name=name,
                    description="Review an approval request.",
                    code="REQUEST_NOT_PENDING",
                    message=(
                        "Only pending approval requests can be reviewed. "
                        "A rejected request must be explicitly retried first."
                    ),
                    status=409,
                    inputs=inputs,
                )

            if request["requested_by"] == actor_id:
                return fail(
                    name=name,
                    description="Review an approval request.",
                    code="SELF_APPROVAL_NOT_ALLOWED",
                    message=(
                        "A requester cannot approve or reject their own request."
                    ),
                    status=403,
                    inputs=inputs,
                )

            item = get_work_item_by_id(
                request["work_item_id"],
                connection=connection,
            )

            if item is None:
                return fail(
                    name=name,
                    description="Review an approval request.",
                    code="WORK_ITEM_NOT_FOUND",
                    message="The associated work item does not exist.",
                    status=404,
                    inputs=inputs,
                )

            if item["status"] != "pending_approval":
                return fail(
                    name=name,
                    description="Review an approval request.",
                    code="INVALID_WORK_ITEM_STATUS",
                    message="The work item is not currently awaiting approval.",
                    status=409,
                    inputs=inputs,
                )

            if not eligible_approver(item["team_id"], actor_id):
                return fail(
                    name=name,
                    description="Review an approval request.",
                    code="FORBIDDEN",
                    message=(
                        "Only a current team lead or designated approver "
                        "may decide this request."
                    ),
                    status=403,
                    inputs=inputs,
                )

            assigned_approver = request.get("approver_id")

            if (
                assigned_approver is not None
                and assigned_approver != actor_id
            ):
                return fail(
                    name=name,
                    description="Review an approval request.",
                    code="NOT_ASSIGNED_APPROVER",
                    message=(
                        "This approval request is assigned to another approver."
                    ),
                    status=403,
                    inputs=inputs,
                )

            reviewed = record_approval_decision_if_pending(
                request_id,
                decision,
                decision_reason=decision_reason,
                connection=connection,
            )

            if reviewed is None:
                raise _ReviewConflict()

            next_work_item_status = (
                "resolved" if decision == "approved" else "in_progress"
            )

            updated_item = update_work_item_status(
                item["id"],
                next_work_item_status,
                expected_updated_at=item["updated_at"],
                connection=connection,
            )

            if updated_item is None:
                raise _ReviewConflict()

            record_work_item_activity(
                connection=connection,
                work_item_id=item["id"],
                actor_id=actor_id,
                action=(
                    "approval_approved"
                    if decision == "approved"
                    else "approval_rejected"
                ),
                details={
                    "approval_request_id": str(request_id),
                    "decision": decision,
                    "decision_reason": decision_reason,
                    "old_work_item_status": "pending_approval",
                    "new_work_item_status": next_work_item_status,
                },
            )

            return success(
                name=name,
                description=(
                    "Approval request approved."
                    if decision == "approved"
                    else (
                        "Approval request rejected. The request remains "
                        "rejected until the requester retries it."
                    )
                ),
                data={
                    "approval_request": public_approval(reviewed),
                    "work_item": {
                        "id": str(updated_item["id"]),
                        "status": updated_item["status"],
                        "completed_at": (
                            updated_item["completed_at"].isoformat()
                            if updated_item.get("completed_at")
                            else None
                        ),
                    },
                },
                inputs=inputs,
            )

        return execute_idempotently(
            user_id=actor_id,
            idempotency_key=idempotency_key,
            operation_name=name,
            category="approvals",
            subcategory="approval_workflow",
            description="Review an approval request.",
            payload={
                "approval_request_id": str(request_id),
                "decision": decision,
                "decision_reason": decision_reason,
            },
            operation=_review,
        )

    except _ReviewConflict:
        return fail(
            name=name,
            description="Review an approval request.",
            code="APPROVAL_STATE_CHANGED",
            message=(
                "The approval request or work item changed while the "
                "decision was being saved. No partial decision was committed."
            ),
            status=409,
            inputs=inputs,
        )
    except ApprovalRelatedRecordNotFoundError:
        return fail(
            name=name,
            description="Review an approval request.",
            code="RELATED_RECORD_NOT_FOUND",
            message=(
                "The approval request or related user could not be found."
            ),
            status=404,
            inputs=inputs,
        )
    except ActivityRelatedRecordNotFoundError:
        return fail(
            name=name,
            description="Review an approval request.",
            code="RELATED_RECORD_NOT_FOUND",
            message="The activity actor or work item could not be found.",
            status=404,
            inputs=inputs,
        )
    except InvalidApprovalRecordError:
        return fail(
            name=name,
            description="Review an approval request.",
            code="INVALID_APPROVAL",
            message="The approval decision is invalid.",
            status=400,
            inputs=inputs,
        )
    except InvalidActivityRecordError:
        return fail(
            name=name,
            description="Review an approval request.",
            code="ACTIVITY_WRITE_FAILED",
            message=(
                "The decision was not committed because its activity "
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
            description="Review an approval request.",
            code="DATABASE_ERROR",
            message="The approval decision could not be saved right now.",
            status=500,
            inputs=inputs,
        )