"""Activity history API routes.

Activity history is read through existing Services. Business workflows
continue recording audit events transactionally inside their Services.

The only client-facing write supported here is a progress note, which
uses a fixed action name rather than accepting arbitrary audit actions.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Header, Query
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

from BACKEND.API.request_dealer import get_verified_actor_id

from BACKEND.Services.activity.create_activity import (
    create_activity as create_activity_service,
)
from BACKEND.Services.activity.get_activity_by_id import (
    get_activity_by_id as get_activity_by_id_service,
)
from BACKEND.Services.activity.get_team_activity import (
    get_team_activity as get_team_activity_service,
)
from BACKEND.Services.activity.get_user_activity import (
    get_user_activity as get_user_activity_service,
)
from BACKEND.Services.activity.get_work_item_activity import (
    get_work_item_activity as get_work_item_activity_service,
)


router = APIRouter(tags=["Activity"])


# ============================================================
# REQUEST MODELS
# ============================================================

class CreateProgressNoteRequest(BaseModel):
    """A user-authored note associated with a work item."""

    model_config = ConfigDict(extra="forbid")

    note: str = Field(min_length=1, max_length=5000)

    @field_validator("note")
    @classmethod
    def validate_note(cls, value: str) -> str:
        value = value.strip()

        if not value:
            raise ValueError("Note cannot be empty.")

        return value


# ============================================================
# RESPONSE ADAPTER
# ============================================================

def _service_response(result: Any) -> JSONResponse:
    """Preserve the existing ServiceResponse envelope and HTTP status."""

    return JSONResponse(
        status_code=result.http_status,
        content=jsonable_encoder(result),
    )


# ============================================================
# WORK-ITEM ACTIVITY TIMELINE
# ============================================================

@router.get("/work-items/{work_item_id}/activity")
def get_work_item_activity(
    work_item_id: str,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    action: str | None = Query(
        default=None,
        min_length=1,
        max_length=50,
    ),
    actor_user_id: str = Depends(get_verified_actor_id),
) -> JSONResponse:
    """Retrieve a paginated, optionally filtered work-item timeline."""

    result = get_work_item_activity_service(
        actor_user_id=actor_user_id,
        work_item_id=work_item_id,
        limit=limit,
        offset=offset,
        action=action,
    )

    return _service_response(result)


# ============================================================
# TEAM ACTIVITY FEED
# ============================================================

@router.get("/teams/{team_id}/activity")
def get_team_activity(
    team_id: str,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    action: str | None = Query(
        default=None,
        min_length=1,
        max_length=50,
    ),
    actor_user_id: str = Depends(get_verified_actor_id),
) -> JSONResponse:
    """Retrieve activity for a team the actor can access."""

    result = get_team_activity_service(
        actor_user_id=actor_user_id,
        team_id=team_id,
        limit=limit,
        offset=offset,
        action=action,
    )

    return _service_response(result)


# ============================================================
# CURRENT USER'S ACTIVITY
# Keep this route before /users/{user_id}/activity.
# ============================================================

@router.get("/users/me/activity")
def get_my_activity(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    action: str | None = Query(
        default=None,
        min_length=1,
        max_length=50,
    ),
    actor_user_id: str = Depends(get_verified_actor_id),
) -> JSONResponse:
    """Retrieve the authenticated user's activity feed."""

    result = get_user_activity_service(
        actor_user_id=actor_user_id,
        user_id=None,
        limit=limit,
        offset=offset,
        action=action,
    )

    return _service_response(result)


# ============================================================
# ANOTHER USER'S ACTIVITY
# ============================================================

@router.get("/users/{user_id}/activity")
def get_user_activity(
    user_id: str,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    action: str | None = Query(
        default=None,
        min_length=1,
        max_length=50,
    ),
    actor_user_id: str = Depends(get_verified_actor_id),
) -> JSONResponse:
    """Retrieve another user's activity, subject to Service authorization."""

    result = get_user_activity_service(
        actor_user_id=actor_user_id,
        user_id=user_id,
        limit=limit,
        offset=offset,
        action=action,
    )

    return _service_response(result)


# ============================================================
# SINGLE ACTIVITY RECORD
# ============================================================

@router.get("/activity/{activity_id}")
def get_activity_by_id(
    activity_id: str,
    actor_user_id: str = Depends(get_verified_actor_id),
) -> JSONResponse:
    """Retrieve a single activity record after access verification."""

    result = get_activity_by_id_service(
        actor_user_id=actor_user_id,
        activity_id=activity_id,
    )

    return _service_response(result)


# ============================================================
# ADD A PROGRESS NOTE
# ============================================================

@router.post("/work-items/{work_item_id}/notes")
def add_progress_note(
    work_item_id: str,
    body: CreateProgressNoteRequest,
    idempotency_key: str | None = Header(
        default=None,
        alias="Idempotency-Key",
    ),
    actor_user_id: str = Depends(get_verified_actor_id),
) -> JSONResponse:
    """Record a progress note in the work item's activity history.

    The client cannot choose the activity action or actor identity.
    The existing Service validates team access and handles idempotency.
    """

    result = create_activity_service(
        actor_user_id=actor_user_id,
        work_item_id=work_item_id,
        action="note_added",
        details={"note": body.note},
        idempotency_key=idempotency_key,
    )

    return _service_response(result)