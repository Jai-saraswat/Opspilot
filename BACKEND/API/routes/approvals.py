"""Approval workflow API routes.

All business rules, authorization, transactional writes, activity recording,
and idempotency remain in the existing Services layer.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Header, Query
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from BACKEND.API.request_dealer import get_verified_actor_id

from BACKEND.Services.approvals.assign_approval_approver import (
    assign_approval_approver as assign_approval_approver_service,
)
from BACKEND.Services.approvals.create_approval_request import (
    create_approval_request as create_approval_request_service,
)
from BACKEND.Services.approvals.get_approval_request import (
    get_approval_request as get_approval_request_service,
)
from BACKEND.Services.approvals.get_pending_approvals import (
    get_pending_approvals as get_pending_approvals_service,
)
from BACKEND.Services.approvals.list_user_approval_requests import (
    get_user_approval_requests as get_user_approval_requests_service,
)
from BACKEND.Services.approvals.list_work_item_approvals import (
    get_work_item_approvals as get_work_item_approvals_service,
)
from BACKEND.Services.approvals.retry_approval_request import (
    retry_approval_request as retry_approval_request_service,
)
from BACKEND.Services.approvals.review_approval_request import (
    review_approval_request as review_approval_request_service,
)


router = APIRouter(tags=["Approvals"])


# ============================================================
# REQUEST MODELS
# ============================================================

class CreateApprovalRequest(BaseModel):
    """Submit an in-progress work item for approval."""

    model_config = ConfigDict(extra="forbid")

    approver_id: str | None = None


class AssignApprovalApproverRequest(BaseModel):
    """Assign, reassign, or clear an approval's approver.

    The field is required, but null is allowed to clear the assignment.
    """

    model_config = ConfigDict(extra="forbid")

    approver_id: str | None = Field(...)


class ReviewApprovalRequest(BaseModel):
    """Approve or reject a pending approval request."""

    model_config = ConfigDict(extra="forbid")

    decision: str
    decision_reason: str | None = None


# ============================================================
# RESPONSE ADAPTER
# ============================================================

def _service_response(result: Any) -> JSONResponse:
    """Preserve the ServiceResponse envelope and intended HTTP status."""

    return JSONResponse(
        status_code=result.http_status,
        content=jsonable_encoder(result),
    )


# ============================================================
# PENDING APPROVAL QUEUE
# ============================================================

@router.get("/approvals/pending")
def get_pending_approvals(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    actor_user_id: str = Depends(get_verified_actor_id),
) -> JSONResponse:
    """Retrieve pending approvals available to the current actor."""

    result = get_pending_approvals_service(
        actor_user_id=actor_user_id,
        limit=limit,
        offset=offset,
    )

    return _service_response(result)


# ============================================================
# REQUESTER APPROVAL HISTORY
# ============================================================

@router.get("/approvals/requests")
def get_user_approval_requests(
    requested_by: str | None = Query(default=None),
    status: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    actor_user_id: str = Depends(get_verified_actor_id),
) -> JSONResponse:
    """List approval requests submitted by a user.

    When requested_by is omitted, the Service returns the current
    actor's own requests. Requests for another user remain subject
    to the existing Service authorization policy.
    """

    result = get_user_approval_requests_service(
        actor_user_id=actor_user_id,
        requested_by=requested_by,
        status=status,
        limit=limit,
        offset=offset,
    )

    return _service_response(result)


# ============================================================
# WORK-ITEM APPROVAL HISTORY
# ============================================================

@router.get("/work-items/{work_item_id}/approvals")
def get_work_item_approvals(
    work_item_id: str,
    status: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    actor_user_id: str = Depends(get_verified_actor_id),
) -> JSONResponse:
    """Retrieve approval history for a particular work item."""

    result = get_work_item_approvals_service(
        actor_user_id=actor_user_id,
        work_item_id=work_item_id,
        status=status,
        limit=limit,
        offset=offset,
    )

    return _service_response(result)


# ============================================================
# CREATE APPROVAL REQUEST
# ============================================================

@router.post("/work-items/{work_item_id}/approvals")
def create_approval_request(
    work_item_id: str,
    body: CreateApprovalRequest,
    idempotency_key: str | None = Header(
        default=None,
        alias="Idempotency-Key",
    ),
    actor_user_id: str = Depends(get_verified_actor_id),
) -> JSONResponse:
    """Submit an eligible work item for approval."""

    result = create_approval_request_service(
        actor_user_id=actor_user_id,
        work_item_id=work_item_id,
        approver_id=body.approver_id,
        idempotency_key=idempotency_key,
    )

    return _service_response(result)


# ============================================================
# RETRIEVE APPROVAL REQUEST
# ============================================================

@router.get("/approvals/{approval_request_id}")
def get_approval_request(
    approval_request_id: str,
    actor_user_id: str = Depends(get_verified_actor_id),
) -> JSONResponse:
    """Retrieve one approval request under the existing access policy."""

    result = get_approval_request_service(
        actor_user_id=actor_user_id,
        approval_request_id=approval_request_id,
    )

    return _service_response(result)


# ============================================================
# ASSIGN OR CHANGE APPROVER
# ============================================================

@router.patch("/approvals/{approval_request_id}/approver")
def assign_approval_approver(
    approval_request_id: str,
    body: AssignApprovalApproverRequest,
    idempotency_key: str | None = Header(
        default=None,
        alias="Idempotency-Key",
    ),
    actor_user_id: str = Depends(get_verified_actor_id),
) -> JSONResponse:
    """Assign, reassign, or clear an approval's approver."""

    result = assign_approval_approver_service(
        actor_user_id=actor_user_id,
        approval_request_id=approval_request_id,
        approver_id=body.approver_id,
        idempotency_key=idempotency_key,
    )

    return _service_response(result)


# ============================================================
# REVIEW APPROVAL REQUEST
# ============================================================

@router.post("/approvals/{approval_request_id}/decision")
def review_approval_request(
    approval_request_id: str,
    body: ReviewApprovalRequest,
    idempotency_key: str | None = Header(
        default=None,
        alias="Idempotency-Key",
    ),
    actor_user_id: str = Depends(get_verified_actor_id),
) -> JSONResponse:
    """Approve or reject a pending approval request."""

    result = review_approval_request_service(
        actor_user_id=actor_user_id,
        approval_request_id=approval_request_id,
        decision=body.decision,
        decision_reason=body.decision_reason,
        idempotency_key=idempotency_key,
    )

    return _service_response(result)


# ============================================================
# RETRY REJECTED APPROVAL
# ============================================================

@router.post("/approvals/{approval_request_id}/retry")
def retry_approval_request(
    approval_request_id: str,
    idempotency_key: str | None = Header(
        default=None,
        alias="Idempotency-Key",
    ),
    actor_user_id: str = Depends(get_verified_actor_id),
) -> JSONResponse:
    """Retry an eligible rejected approval request."""

    result = retry_approval_request_service(
        actor_user_id=actor_user_id,
        approval_request_id=approval_request_id,
        idempotency_key=idempotency_key,
    )

    return _service_response(result)