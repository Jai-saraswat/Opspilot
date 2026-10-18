"""Submit a work item for approval in one transaction."""

from __future__ import annotations

from uuid import UUID

from BACKEND.Postgres.Operations.activity.errors import (
    ActivityDatabaseError,
    ActivityRelatedRecordNotFoundError,
    InvalidActivityRecordError,
)
from BACKEND.Postgres.Operations.approvals.create_approval_request import (
    create_approval_request as create_approval_operation,
)
from BACKEND.Postgres.Operations.approvals.errors import (
    ApprovalDatabaseError,
    ApprovalRelatedRecordNotFoundError,
)
from BACKEND.Postgres.Operations.approvals.list_work_item_approvals import (
    list_work_item_approvals,
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
    is_team_member,
    parse_identifier,
    public_approval,
    record_work_item_activity,
    success,
)
from BACKEND.Services.idempotency import execute_idempotently


class _ApprovalWorkflowConflict(Exception):
    """Roll back partial workflow writes."""


def create_approval_request(
    *,
    actor_user_id: UUID | str,
    work_item_id: UUID | str,
    approver_id: UUID | str | None = None,
    idempotency_key: str | None = None,
):
    """Submit an in-progress work item for approval.

    A rejected request must be retried via retry_approval_request.
    """
    name = "create_approval_request"
    inputs = {"work_item_id": str(work_item_id)}

    actor_id = active_actor(actor_user_id)
    if actor_id is None:
        return fail(
            name=name,
            description="Submit a work item for approval.",
            code="UNAUTHENTICATED",
            message="An active user account is required.",
            status=401,
            inputs=inputs,
        )

    try:
        item_id = parse_identifier(work_item_id)
        target_approver_id = (
            parse_identifier(approver_id)
            if approver_id is not None
            else None
        )
    except (ValueError, TypeError, AttributeError):
        return fail(
            name=name,
            description="Submit a work item for approval.",
            code="INVALID_IDENTIFIER",
            message="The work-item or approver identifier is invalid.",
            status=400,
            inputs=inputs,
        )

    if target_approver_id == actor_id:
        return fail(
            name=name,
            description="Submit a work item for approval.",
            code="SELF_APPROVAL_NOT_ALLOWED",
            message="A requester cannot be their own approver.",
            status=400,
            inputs=inputs,
        )

    try:
        def _create(connection):
            item = get_work_item_by_id(
                item_id,
                connection=connection,
            )

            if item is None:
                return fail(
                    name=name,
                    description="Submit a work item for approval.",
                    code="WORK_ITEM_NOT_FOUND",
                    message="The work item does not exist.",
                    status=404,
                    inputs=inputs,
                )

            team_id = item["team_id"]

            if not is_team_member(team_id, actor_id):
                return fail(
                    name=name,
                    description="Submit a work item for approval.",
                    code="FORBIDDEN",
                    message="You must be a member of the work item's team.",
                    status=403,
                    inputs=inputs,
                )

            if item["status"] != "in_progress":
                return fail(
                    name=name,
                    description="Submit a work item for approval.",
                    code="INVALID_WORK_ITEM_STATUS",
                    message=(
                        "Only an in-progress work item can be submitted "
                        "for approval."
                    ),
                    status=409,
                    inputs=inputs,
                )

            if (
                target_approver_id is not None
                and not eligible_approver(team_id, target_approver_id)
            ):
                return fail(
                    name=name,
                    description="Submit a work item for approval.",
                    code="INVALID_APPROVER",
                    message=(
                        "The approver must be an active team lead or "
                        "member with the approver role."
                    ),
                    status=400,
                    inputs=inputs,
                )

            pending = list_work_item_approvals(
                item_id,
                status="pending",
                limit=1,
                offset=0,
                connection=connection,
            )

            if pending["total"]:
                return fail(
                    name=name,
                    description="Submit a work item for approval.",
                    code="PENDING_REQUEST_EXISTS",
                    message=(
                        "This work item already has a pending "
                        "approval request."
                    ),
                    status=409,
                    inputs=inputs,
                )

            rejected = list_work_item_approvals(
                item_id,
                status="rejected",
                limit=1,
                offset=0,
                connection=connection,
            )

            if rejected["total"]:
                return fail(
                    name=name,
                    description="Submit a work item for approval.",
                    code="RETRY_REQUIRED",
                    message=(
                        "This work item has a rejected approval request. "
                        "Use retry_approval_request to reopen that request."
                    ),
                    status=409,
                    inputs=inputs,
                )

            request = create_approval_operation(
                work_item_id=item_id,
                requested_by=actor_id,
                approver_id=target_approver_id,
                connection=connection,
            )

            updated_item = update_work_item_status(
                item_id,
                "pending_approval",
                expected_updated_at=item["updated_at"],
                connection=connection,
            )

            if updated_item is None:
                raise _ApprovalWorkflowConflict()

            record_work_item_activity(
                connection=connection,
                work_item_id=item_id,
                actor_id=actor_id,
                action="approval_requested",
                details={
                    "approval_request_id": str(request["id"]),
                    "approver_id": (
                        str(target_approver_id)
                        if target_approver_id
                        else None
                    ),
                },
            )

            return success(
                name=name,
                description="Approval request submitted.",
                data={"approval_request": public_approval(request)},
                status=201,
                inputs=inputs,
            )

        return execute_idempotently(
            user_id=actor_id,
            idempotency_key=idempotency_key,
            operation_name=name,
            category="approvals",
            subcategory="approval_workflow",
            description="Submit a work item for approval.",
            payload={
                "work_item_id": str(item_id),
                "approver_id": (
                    str(target_approver_id)
                    if target_approver_id is not None
                    else None
                ),
            },
            operation=_create,
        )

    except _ApprovalWorkflowConflict:
        return fail(
            name=name,
            description="Submit a work item for approval.",
            code="WORK_ITEM_CHANGED",
            message=(
                "The work item changed while the approval request was "
                "being submitted. No request was committed; retrieve "
                "the latest item and retry."
            ),
            status=409,
            inputs=inputs,
        )
    except (
        ApprovalRelatedRecordNotFoundError,
        ActivityRelatedRecordNotFoundError,
    ):
        return fail(
            name=name,
            description="Submit a work item for approval.",
            code="RELATED_RECORD_NOT_FOUND",
            message=(
                "The work item, requester, approver, or activity reference "
                "could not be found."
            ),
            status=404,
            inputs=inputs,
        )
    except InvalidActivityRecordError:
        return fail(
            name=name,
            description="Submit a work item for approval.",
            code="ACTIVITY_WRITE_FAILED",
            message=(
                "The request was not committed because its activity event "
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
            description="Submit a work item for approval.",
            code="DATABASE_ERROR",
            message="The approval request could not be submitted right now.",
            status=500,
            inputs=inputs,
        )