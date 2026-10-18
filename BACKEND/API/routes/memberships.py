"""Team membership API routes.

All business rules, membership authorization, and database operations
remain in the existing Services layer.
"""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from BACKEND.API.request_dealer import get_verified_actor_id

from BACKEND.Services.teams.memberships.add_team_member import (
    add_team_member as add_team_member_service,
)
from BACKEND.Services.teams.memberships.get_membership import (
    get_membership as get_membership_service,
)
from BACKEND.Services.teams.memberships.list_team_members import (
    list_team_members as list_team_members_service,
)
from BACKEND.Services.teams.memberships.list_user_teams import (
    list_user_teams as list_user_teams_service,
)
from BACKEND.Services.teams.memberships.remove_team_member import (
    remove_team_member as remove_team_member_service,
)
from BACKEND.Services.teams.memberships.update_membership_role import (
    update_membership_role as update_membership_role_service,
)


router = APIRouter(tags=["Team Memberships"])


# ============================================================
# REQUEST MODELS
# ============================================================

TeamRole = Literal["lead", "member", "approver"]


class AddTeamMemberRequest(BaseModel):
    """Add an existing user to a team."""

    model_config = ConfigDict(extra="forbid")

    user_id: UUID
    role: TeamRole = "member"


class UpdateMembershipRoleRequest(BaseModel):
    """Change a member's role within a team."""

    model_config = ConfigDict(extra="forbid")

    role: TeamRole


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
# CURRENT USER'S TEAMS
# ============================================================

@router.get("/users/me/teams")
def list_my_teams(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    search: str | None = Query(default=None),
    actor_user_id: str = Depends(get_verified_actor_id),
) -> JSONResponse:
    """List teams belonging to the authenticated user."""

    result = list_user_teams_service(
        actor_user_id=actor_user_id,
        limit=limit,
        offset=offset,
        search=search,
    )

    return _service_response(result)


@router.get("/users/{user_id}/teams")
def list_user_teams(
    user_id: UUID,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    search: str | None = Query(default=None),
    actor_user_id: str = Depends(get_verified_actor_id),
) -> JSONResponse:
    """List a user's teams through the existing authorization policy."""

    result = list_user_teams_service(
        actor_user_id=actor_user_id,
        user_id=str(user_id),
        limit=limit,
        offset=offset,
        search=search,
    )

    return _service_response(result)


# ============================================================
# LIST TEAM MEMBERS
# ============================================================

@router.get("/teams/{team_id}/members")
def list_team_members(
    team_id: UUID,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    role: TeamRole | None = Query(default=None),
    search: str | None = Query(default=None),
    actor_user_id: str = Depends(get_verified_actor_id),
) -> JSONResponse:
    """List, filter, and search members of a team."""

    result = list_team_members_service(
        actor_user_id=actor_user_id,
        team_id=str(team_id),
        limit=limit,
        offset=offset,
        role=role,
        search=search,
    )

    return _service_response(result)


# ============================================================
# ADD TEAM MEMBER
# ============================================================

@router.post("/teams/{team_id}/members")
def add_team_member(
    team_id: UUID,
    body: AddTeamMemberRequest,
    idempotency_key: str | None = Header(
        default=None,
        alias="Idempotency-Key",
    ),
    actor_user_id: str = Depends(get_verified_actor_id),
) -> JSONResponse:
    """Add an existing active user to a team."""

    result = add_team_member_service(
        actor_user_id=actor_user_id,
        team_id=str(team_id),
        user_id=str(body.user_id),
        role=body.role,
        idempotency_key=idempotency_key,
    )

    return _service_response(result)


# ============================================================
# GET A SPECIFIC MEMBERSHIP
# ============================================================

@router.get("/teams/{team_id}/members/{user_id}")
def get_membership(
    team_id: UUID,
    user_id: UUID,
    actor_user_id: str = Depends(get_verified_actor_id),
) -> JSONResponse:
    """Retrieve a specific user's membership in a team."""

    result = get_membership_service(
        actor_user_id=actor_user_id,
        team_id=str(team_id),
        user_id=str(user_id),
    )

    return _service_response(result)


# ============================================================
# CHANGE MEMBERSHIP ROLE
# ============================================================

@router.patch("/teams/{team_id}/members/{user_id}/role")
def update_membership_role(
    team_id: UUID,
    user_id: UUID,
    body: UpdateMembershipRoleRequest,
    idempotency_key: str | None = Header(
        default=None,
        alias="Idempotency-Key",
    ),
    actor_user_id: str = Depends(get_verified_actor_id),
) -> JSONResponse:
    """Change a user's role within a team."""

    result = update_membership_role_service(
        actor_user_id=actor_user_id,
        team_id=str(team_id),
        user_id=str(user_id),
        role=body.role,
        idempotency_key=idempotency_key,
    )

    return _service_response(result)


# ============================================================
# REMOVE TEAM MEMBER
# ============================================================

@router.delete("/teams/{team_id}/members/{user_id}")
def remove_team_member(
    team_id: UUID,
    user_id: UUID,
    idempotency_key: str | None = Header(
        default=None,
        alias="Idempotency-Key",
    ),
    actor_user_id: str = Depends(get_verified_actor_id),
) -> JSONResponse:
    """Remove a member without bypassing team-lead safeguards."""

    result = remove_team_member_service(
        actor_user_id=actor_user_id,
        team_id=str(team_id),
        user_id=str(user_id),
        idempotency_key=idempotency_key,
    )

    return _service_response(result)