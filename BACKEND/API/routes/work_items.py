"""Work-item API routes.

All business rules and persistence operations remain in Services.
The API validates request shapes, identifies the authenticated actor,
forwards relevant headers, and preserves ServiceResponse semantics.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Header, Query
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from BACKEND.API.request_dealer import get_verified_actor_id

from BACKEND.Services.work_management.create_work_item import (
    create_work_item as create_work_item_service,
)
from BACKEND.Services.work_management.get_team_work_items import (
    get_team_work_items as get_team_work_items_service,
)
from BACKEND.Services.work_management.get_user_work_items import (
    get_user_work_items as get_user_work_items_service,
)
from BACKEND.Services.work_management.get_work_item import (
    get_work_item as get_work_item_service,
)
from BACKEND.Services.work_management.list_work_items import (
    list_work_items as list_work_items_service,
)
from BACKEND.Services.work_management.update_work_item import (
    update_work_item as update_work_item_service,
)
from BACKEND.Services.work_management.claim_work_item import (
    claim_work_item as claim_work_item_service,
)
from BACKEND.Services.work_management.assign_work_item import (
    assign_work_item as assign_work_item_service,
)
from BACKEND.Services.work_management.change_work_item_status import (
    change_work_item_status as change_work_item_status_service,
)
from BACKEND.Services.work_management.change_work_item_priority import (
    change_work_item_priority as change_work_item_priority_service,
)


router = APIRouter(tags=["Work Items"])


# ============================================================
# REQUEST MODELS
# ============================================================

class CreateWorkItemRequest(BaseModel):
    """Create an operational work item."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1)
    type: str
    team_id: str
    priority: str = "medium"
    assignee_id: str | None = None


class UpdateWorkItemRequest(BaseModel):
    """Update editable work-item details.

    expected_updated_at must be the exact timestamp returned by the API.
    Keep it as a string to avoid unnecessary timestamp reformatting.
    """

    model_config = ConfigDict(extra="forbid")

    expected_updated_at: str = Field(min_length=1)
    title: str | None = None
    description: str | None = None
    type: str | None = None


class ClaimWorkItemRequest(BaseModel):
    """Claim requires the version the client last observed."""

    model_config = ConfigDict(extra="forbid")

    expected_updated_at: str = Field(min_length=1)


class AssignWorkItemRequest(BaseModel):
    """Assign, reassign, or unassign a work item.

    assignee_id is required in the request, but may be null to unassign.
    """

    model_config = ConfigDict(extra="forbid")

    assignee_id: str | None = Field(...)
    expected_updated_at: str = Field(min_length=1)


class ChangeWorkItemStatusRequest(BaseModel):
    """Request a workflow status transition."""

    model_config = ConfigDict(extra="forbid")

    status: str
    expected_updated_at: str = Field(min_length=1)


class ChangeWorkItemPriorityRequest(BaseModel):
    """Request a priority change."""

    model_config = ConfigDict(extra="forbid")

    priority: str
    expected_updated_at: str = Field(min_length=1)


# ============================================================
# RESPONSE ADAPTER
# ============================================================

def _service_response(result: Any) -> JSONResponse:
    """Preserve the established ServiceResponse envelope and status."""

    return JSONResponse(
        status_code=result.http_status,
        content=jsonable_encoder(result),
    )


# ============================================================
# LIST AND SEARCH WORK ITEMS
# ============================================================

@router.get("/work-items")
def list_work_items(
    team_id: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    assignee_id: str | None = Query(default=None),
    unassigned_only: bool = Query(default=False),
    status: str | None = Query(default=None),
    priority: str | None = Query(default=None),
    type: str | None = Query(default=None),
    search: str | None = Query(default=None),
    actor_user_id: str = Depends(get_verified_actor_id),
) -> JSONResponse:
    """List searchable work items within the permitted scope.

    Without team_id, the existing Service requires appropriate global
    listing/read permission. The API does not bypass this restriction.
    """

    result = list_work_items_service(
        actor_user_id=actor_user_id,
        team_id=team_id,
        limit=limit,
        offset=offset,
        assignee_id=assignee_id,
        unassigned_only=unassigned_only,
        status=status,
        priority=priority,
        type=type,
        search=search,
    )

    return _service_response(result)


# This static route must be declared before /work-items/{work_item_id}.
@router.get("/work-items/mine")
def list_my_work_items(
    team_id: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    status: str | None = Query(default=None),
    priority: str | None = Query(default=None),
    type: str | None = Query(default=None),
    search: str | None = Query(default=None),
    actor_user_id: str = Depends(get_verified_actor_id),
) -> JSONResponse:
    """List work assigned to the authenticated user."""

    result = get_user_work_items_service(
        actor_user_id=actor_user_id,
        user_id=None,
        team_id=team_id,
        limit=limit,
        offset=offset,
        status=status,
        priority=priority,
        type=type,
        search=search,
    )

    return _service_response(result)


@router.get("/teams/{team_id}/work-items")
def list_team_work_items(
    team_id: str,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    assignee_id: str | None = Query(default=None),
    unassigned_only: bool = Query(default=False),
    status: str | None = Query(default=None),
    priority: str | None = Query(default=None),
    type: str | None = Query(default=None),
    search: str | None = Query(default=None),
    actor_user_id: str = Depends(get_verified_actor_id),
) -> JSONResponse:
    """List work for a specific team."""

    result = get_team_work_items_service(
        actor_user_id=actor_user_id,
        team_id=team_id,
        limit=limit,
        offset=offset,
        assignee_id=assignee_id,
        unassigned_only=unassigned_only,
        status=status,
        priority=priority,
        type=type,
        search=search,
    )

    return _service_response(result)


@router.get("/users/{user_id}/work-items")
def list_user_work_items(
    user_id: str,
    team_id: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    status: str | None = Query(default=None),
    priority: str | None = Query(default=None),
    type: str | None = Query(default=None),
    search: str | None = Query(default=None),
    actor_user_id: str = Depends(get_verified_actor_id),
) -> JSONResponse:
    """List a user's assigned work through Service authorization."""

    result = get_user_work_items_service(
        actor_user_id=actor_user_id,
        user_id=user_id,
        team_id=team_id,
        limit=limit,
        offset=offset,
        status=status,
        priority=priority,
        type=type,
        search=search,
    )

    return _service_response(result)


# ============================================================
# CREATE WORK ITEM
# ============================================================

@router.post("/work-items")
def create_work_item(
    body: CreateWorkItemRequest,
    idempotency_key: str | None = Header(
        default=None,
        alias="Idempotency-Key",
    ),
    actor_user_id: str = Depends(get_verified_actor_id),
) -> JSONResponse:
    """Create a work item and its activity through the Service."""

    result = create_work_item_service(
        actor_user_id=actor_user_id,
        title=body.title,
        description=body.description,
        type=body.type,
        team_id=body.team_id,
        priority=body.priority,
        assignee_id=body.assignee_id,
        idempotency_key=idempotency_key,
    )

    return _service_response(result)


# ============================================================
# RETRIEVE WORK ITEM
# ============================================================

@router.get("/work-items/{work_item_id}")
def get_work_item(
    work_item_id: str,
    actor_user_id: str = Depends(get_verified_actor_id),
) -> JSONResponse:
    """Retrieve one work item under the existing access policy."""

    result = get_work_item_service(
        actor_user_id=actor_user_id,
        work_item_id=work_item_id,
    )

    return _service_response(result)


# ============================================================
# UPDATE WORK-ITEM DETAILS
# ============================================================

@router.patch("/work-items/{work_item_id}")
def update_work_item(
    work_item_id: str,
    body: UpdateWorkItemRequest,
    idempotency_key: str | None = Header(
        default=None,
        alias="Idempotency-Key",
    ),
    actor_user_id: str = Depends(get_verified_actor_id),
) -> JSONResponse:
    """Update details using optimistic concurrency protection."""

    result = update_work_item_service(
        actor_user_id=actor_user_id,
        work_item_id=work_item_id,
        expected_updated_at=body.expected_updated_at,
        title=body.title,
        description=body.description,
        type=body.type,
        idempotency_key=idempotency_key,
    )

    return _service_response(result)


# ============================================================
# CLAIM WORK ITEM
# ============================================================

@router.post("/work-items/{work_item_id}/claim")
def claim_work_item(
    work_item_id: str,
    body: ClaimWorkItemRequest,
    idempotency_key: str | None = Header(
        default=None,
        alias="Idempotency-Key",
    ),
    actor_user_id: str = Depends(get_verified_actor_id),
) -> JSONResponse:
    """Atomically claim an unassigned work item."""

    result = claim_work_item_service(
        actor_user_id=actor_user_id,
        work_item_id=work_item_id,
        expected_updated_at=body.expected_updated_at,
        idempotency_key=idempotency_key,
    )

    return _service_response(result)


# ============================================================
# ASSIGN, REASSIGN, OR UNASSIGN
# ============================================================

@router.patch("/work-items/{work_item_id}/assignee")
def assign_work_item(
    work_item_id: str,
    body: AssignWorkItemRequest,
    idempotency_key: str | None = Header(
        default=None,
        alias="Idempotency-Key",
    ),
    actor_user_id: str = Depends(get_verified_actor_id),
) -> JSONResponse:
    """Assign, reassign, or unassign a work item."""

    result = assign_work_item_service(
        actor_user_id=actor_user_id,
        work_item_id=work_item_id,
        assignee_id=body.assignee_id,
        expected_updated_at=body.expected_updated_at,
        idempotency_key=idempotency_key,
    )

    return _service_response(result)


# ============================================================
# CHANGE STATUS
# ============================================================

@router.patch("/work-items/{work_item_id}/status")
def change_work_item_status(
    work_item_id: str,
    body: ChangeWorkItemStatusRequest,
    idempotency_key: str | None = Header(
        default=None,
        alias="Idempotency-Key",
    ),
    actor_user_id: str = Depends(get_verified_actor_id),
) -> JSONResponse:
    """Request a status transition through the existing workflow."""

    result = change_work_item_status_service(
        actor_user_id=actor_user_id,
        work_item_id=work_item_id,
        status=body.status,
        expected_updated_at=body.expected_updated_at,
        idempotency_key=idempotency_key,
    )

    return _service_response(result)


# ============================================================
# CHANGE PRIORITY
# ============================================================

@router.patch("/work-items/{work_item_id}/priority")
def change_work_item_priority(
    work_item_id: str,
    body: ChangeWorkItemPriorityRequest,
    idempotency_key: str | None = Header(
        default=None,
        alias="Idempotency-Key",
    ),
    actor_user_id: str = Depends(get_verified_actor_id),
) -> JSONResponse:
    """Change priority using the existing concurrency safeguards."""

    result = change_work_item_priority_service(
        actor_user_id=actor_user_id,
        work_item_id=work_item_id,
        priority=body.priority,
        expected_updated_at=body.expected_updated_at,
        idempotency_key=idempotency_key,
    )

    return _service_response(result)