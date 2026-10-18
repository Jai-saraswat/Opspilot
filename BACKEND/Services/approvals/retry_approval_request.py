"""Retry a rejected approval request by reopening the same database row."""

from __future__ import annotations

from uuid import UUID

from BACKEND.Postgres.Operations.activity.errors import (
    ActivityDatabaseError,
    ActivityRelatedRecordNotFoundError,
    InvalidActivityRecordError,
)
from BACKEND.Postgres.Operations.approvals.errors import ApprovalDatabaseError
from BACKEND.Postgres.Operations.approvals.get_approval_request_by_id import (
    get_approval_request_by_id,
)
from BACKEND.Postgres.Operations.approvals.retry_rejected_approval_request import (
    retry_rejected_approval_request as retry_rejected_operation,
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
    fail,
    is_team_member,
    parse_identifier,
    public_approval,
    record_work_item_activity,
    success,
)
from BACKEND.Services.idempotency import execute_idempotently


class _RetryConflict(Exception):
    """Roll back if the request or item cannot be retried atomically."""


def retry_approval_request(
    *,
    actor_user_id: UUID | str,
    approval_request_id: UUID | str,
    idempotency_key: str | None = None,
):
    name = "retry_approval_request"
    inputs = {"approval_request_id": str(approval_request_id)}

    actor_id = active_actor(actor_user_id)
    if actor_id is None:
        return fail(
            name=name,
            description="Retry a rejected approval request.",
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
            description="Retry a rejected approval request.",
            code="INVALID_APPROVAL_ID",
            message="The approval-request identifier is invalid.",
            status=400,
            inputs=inputs,
        )

    try:
        def _retry(connection):
            request = get_approval_request_by_id(
                request_id,
                connection=connection,
            )

            if request is None:
                return fail(
                    name=name,
                    description="Retry a rejected approval request.",
                    code="APPROVAL_NOT_FOUND",
                    message="The approval request does not exist.",
                    status=404,
                    inputs=inputs,
                )

            if request["requested_by"] != actor_id:
                return fail(
                    name=name,
                    description="Retry a rejected approval request.",
                    code="FORBIDDEN",
                    message=(
                        "Only the original requester may retry "
                        "this approval request."
                    ),
                    status=403,
                    inputs=inputs,
                )

            if request["status"] != "rejected":
                return fail(
                    name=name,
                    description="Retry a rejected approval request.",
                    code="REQUEST_NOT_REJECTED",
                    message=(
                        "Only a rejected approval request can be retried."
                    ),
                    status=409,
                    inputs=inputs,
                )

            item_id = request["work_item_id"]
            item = get_work_item_by_id(
                item_id,
                connection=connection,
            )

            if item is None:
                return fail(
                    name=name,
                    description="Retry a rejected approval request.",
                    code="WORK_ITEM_NOT_FOUND",
                    message="The associated work item does not exist.",
                    status=404,
                    inputs=inputs,
                )

            if not is_team_member(item["team_id"], actor_id):
                return fail(
                    name=name,
                    description="Retry a rejected approval request.",
                    code="FORBIDDEN",
                    message=(
                        "You must still be a member of the work item's "
                        "team to retry it."
                    ),
                    status=403,
                    inputs=inputs,
                )

            if item["status"] != "in_progress":
                return fail(
                    name=name,
                    description="Retry a rejected approval request.",
                    code="INVALID_WORK_ITEM_STATUS",
                    message=(
                        "The work item must be in progress before the "
                        "rejected request can be retried."
                    ),
                    status=409,
                    inputs=inputs,
                )

            previous_reason = request.get("decision_reason")
            previous_decided_at = request.get("decided_at")

            reopened = retry_rejected_operation(
                request_id,
                connection=connection,
            )

            if reopened is None:
                raise _RetryConflict()

            updated_item = update_work_item_status(
                item_id,
                "pending_approval",
                expected_updated_at=item["updated_at"],
                connection=connection,
            )

            if updated_item is None:
                raise _RetryConflict()

            record_work_item_activity(
                connection=connection,
                work_item_id=item_id,
                actor_id=actor_id,
                action="approval_retried",
                details={
                    "approval_request_id": str(request_id),
                    "previous_status": "rejected",
                    "previous_decision_reason": previous_reason,
                    "previous_decided_at": (
                        previous_decided_at.isoformat()
                        if previous_decided_at
                        else None
                    ),
                    "new_status": "pending",
                },
            )

            return success(
                name=name,
                description="Rejected approval request retried.",
                data={"approval_request": public_approval(reopened)},
                inputs=inputs,
            )

        return execute_idempotently(
            user_id=actor_id,
            idempotency_key=idempotency_key,
            operation_name=name,
            category="approvals",
            subcategory="approval_workflow",
            description="Retry a rejected approval request.",
            payload={
                "approval_request_id": str(request_id),
            },
            operation=_retry,
        )

    except _RetryConflict:
        return fail(
            name=name,
            description="Retry a rejected approval request.",
            code="APPROVAL_STATE_CHANGED",
            message=(
                "The approval request or work item changed while retrying. "
                "No changes were committed."
            ),
            status=409,
            inputs=inputs,
        )
    except ActivityRelatedRecordNotFoundError:
        return fail(
            name=name,
            description="Retry a rejected approval request.",
            code="RELATED_RECORD_NOT_FOUND",
            message="The work item or activity actor could not be found.",
            status=404,
            inputs=inputs,
        )
    except InvalidActivityRecordError:
        return fail(
            name=name,
            description="Retry a rejected approval request.",
            code="ACTIVITY_WRITE_FAILED",
            message=(
                "The retry was not committed because its activity event "
                "could not be recorded."
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
            description="Retry a rejected approval request.",
            code="DATABASE_ERROR",
            message="The approval request could not be retried right now.",
            status=500,
            inputs=inputs,
        )