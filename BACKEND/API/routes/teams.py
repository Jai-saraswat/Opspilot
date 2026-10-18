"""Team management API routes.

Responsibilities:
- Validate HTTP request parameters and bodies.
- Obtain the authenticated actor from the shared request dealer.
- Delegate business rules and authorization to existing Services.
- Preserve ServiceResponse envelopes and HTTP status codes.

No database access or business-policy duplication belongs here.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Header, Query
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from BACKEND.API.request_dealer import get_verified_actor_id

from BACKEND.Services.teams.create_team import (
    create_team as create_team_service,
)
from BACKEND.Services.teams.delete_team import (
    delete_team as delete_team_service,
)
from BACKEND.Services.teams.get_team_by_id import (
    get_team_by_id as get_team_by_id_service,
)
from BACKEND.Services.teams.get_team_by_name import (
    get_team_by_name as get_team_by_name_service,
)
from BACKEND.Services.teams.list_teams import (
    list_teams as list_teams_service,
)
from BACKEND.Services.teams.update_team import (
    update_team as update_team_service,
)


router = APIRouter(
    prefix="/teams",
    tags=["Teams"],
)


# ============================================================
# REQUEST MODELS
# ============================================================

class CreateTeamRequest(BaseModel):
    """Create a team."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=100)
    description: str | None = None


class UpdateTeamRequest(BaseModel):
    """Update supplied team fields.

    Omitted fields remain unchanged.
    An explicit null description clears the description.
    """

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, max_length=100)
    description: str | None = None


# ============================================================
# RESPONSE ADAPTER
# ============================================================

def _service_response(result: Any) -> JSONResponse:
    """Preserve the existing ServiceResponse contract."""

    return JSONResponse(
        status_code=result.http_status,
        content=jsonable_encoder(result),
    )


# ============================================================
# CREATE TEAM
# ============================================================

@router.post("")
def create_team(
    body: CreateTeamRequest,
    idempotency_key: str | None = Header(
        default=None,
        alias="Idempotency-Key",
    ),
    actor_user_id: str = Depends(get_verified_actor_id),
) -> JSONResponse:
    """Create a team and establish the creator's lead membership."""

    result = create_team_service(
        actor_user_id=actor_user_id,
        name=body.name,
        description=body.description,
        idempotency_key=idempotency_key,
    )

    return _service_response(result)


# ============================================================
# LIST AND SEARCH TEAMS
# ============================================================

@router.get("")
def list_teams(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    search: str | None = Query(default=None),
    actor_user_id: str = Depends(get_verified_actor_id),
) -> JSONResponse:
    """List visible teams with server-side search and pagination."""

    result = list_teams_service(
        actor_user_id=actor_user_id,
        limit=limit,
        offset=offset,
        search=search,
    )

    return _service_response(result)


# This static route must be registered before /{team_id}.
@router.get("/by-name")
def get_team_by_name(
    name: str = Query(..., min_length=1, max_length=100),
    actor_user_id: str = Depends(get_verified_actor_id),
) -> JSONResponse:
    """Retrieve a team by its exact name."""

    result = get_team_by_name_service(
        actor_user_id=actor_user_id,
        name=name,
    )

    return _service_response(result)


# ============================================================
# RETRIEVE TEAM
# ============================================================

@router.get("/{team_id}")
def get_team(
    team_id: str,
    actor_user_id: str = Depends(get_verified_actor_id),
) -> JSONResponse:
    """Retrieve team details with resource-level authorization."""

    result = get_team_by_id_service(
        actor_user_id=actor_user_id,
        team_id=team_id,
    )

    return _service_response(result)


# ============================================================
# UPDATE TEAM
# ============================================================

@router.patch("/{team_id}")
def update_team(
    team_id: str,
    body: UpdateTeamRequest,
    idempotency_key: str | None = Header(
        default=None,
        alias="Idempotency-Key",
    ),
    actor_user_id: str = Depends(get_verified_actor_id),
) -> JSONResponse:
    """Update supplied team fields through the existing Service."""

    service_arguments: dict[str, Any] = {
        "actor_user_id": actor_user_id,
        "team_id": team_id,
        "idempotency_key": idempotency_key,
    }

    # Preserve the difference between an omitted field and a
    # field explicitly included in the PATCH request.
    if "name" in body.model_fields_set:
        service_arguments["name"] = body.name

    if "description" in body.model_fields_set:
        service_arguments["description"] = body.description

    result = update_team_service(**service_arguments)

    return _service_response(result)


# ============================================================
# DELETE TEAM
# ============================================================

@router.delete("/{team_id}")
def delete_team(
    team_id: str,
    idempotency_key: str | None = Header(
        default=None,
        alias="Idempotency-Key",
    ),
    actor_user_id: str = Depends(get_verified_actor_id),
) -> JSONResponse:
    """Delete a team when the existing Service permits it."""

    result = delete_team_service(
        actor_user_id=actor_user_id,
        team_id=team_id,
        idempotency_key=idempotency_key,
    )

    return _service_response(result)