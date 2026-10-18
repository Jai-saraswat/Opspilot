"""Add an existing user to a team."""

from __future__ import annotations

import logging
from uuid import UUID

from BACKEND.Postgres.Operations.teams.get_team_by_id import (
    get_team_by_id as get_team_op,
)
from BACKEND.Postgres.Operations.users.get_user_by_id import get_user_by_id
from BACKEND.Postgres.Operations.memberships.add_team_member import (
    add_team_member as add_member_op,
)
from BACKEND.Postgres.Operations.memberships.errors import (
    InvalidMembershipRecordError,
    MembershipAlreadyExistsError,
    MembershipDatabaseError,
    MembershipRelatedRecordNotFoundError,
)
from BACKEND.Services.idempotency import execute_idempotently
from BACKEND.Services.teams._common import active_actor, parse_uuid

from ._common import (
    can_manage_members,
    fail,
    public_membership,
    success,
    validate_role,
)

logger = logging.getLogger(__name__)

DESCRIPTION = "Add an existing user to a team with a valid team role."


def add_team_member(
    *,
    actor_user_id: UUID | str,
    team_id: UUID | str,
    user_id: UUID | str,
    role: str = "member",
    idempotency_key: str | None = None,
):
    try:
        actor_id = active_actor(actor_user_id)
        target_team_id = parse_uuid(team_id)
        target_user_id = parse_uuid(user_id)
    except (TypeError, ValueError, AttributeError):
        return fail(
            name="add_team_member",
            description=DESCRIPTION,
            code="INVALID_IDENTIFIER",
            message="Valid actor, team and user identifiers are required.",
            status=400,
        )

    if actor_id is None:
        return fail(
            name="add_team_member",
            description=DESCRIPTION,
            code="UNAUTHENTICATED",
            message="An active authenticated account is required.",
            status=401,
        )

    if not validate_role(role):
        return fail(
            name="add_team_member",
            description=DESCRIPTION,
            code="INVALID_MEMBERSHIP_ROLE",
            message="Role must be lead, member or approver.",
            status=400,
        )

    inputs = {
        "team_id": str(target_team_id),
        "user_id": str(target_user_id),
        "role": role,
    }

    try:
        def _add(connection):
            team = get_team_op(
                target_team_id,
                connection=connection,
            )

            if team is None:
                return fail(
                    name="add_team_member",
                    description=DESCRIPTION,
                    code="TEAM_NOT_FOUND",
                    message="The team was not found.",
                    status=404,
                    inputs=inputs,
                )

            if not can_manage_members(actor_id, target_team_id):
                return fail(
                    name="add_team_member",
                    description=DESCRIPTION,
                    code="FORBIDDEN",
                    message=(
                        "Only a team lead or authorized administrator "
                        "can add members."
                    ),
                    status=403,
                    inputs=inputs,
                )

            user = get_user_by_id(
                target_user_id,
                connection=connection,
            )

            if (
                not user
                or user.get("account_status", "active") != "active"
            ):
                return fail(
                    name="add_team_member",
                    description=DESCRIPTION,
                    code="USER_NOT_FOUND",
                    message="An active user account was not found.",
                    status=404,
                    inputs=inputs,
                )

            membership = add_member_op(
                team_id=target_team_id,
                user_id=target_user_id,
                role=role,
                connection=connection,
            )

            return success(
                name="add_team_member",
                description=DESCRIPTION,
                data={"membership": public_membership(membership)},
                inputs=inputs,
                status=201,
            )

        return execute_idempotently(
            user_id=actor_id,
            idempotency_key=idempotency_key,
            operation_name="add_team_member",
            category="teams",
            subcategory="team_memberships",
            description=DESCRIPTION,
            payload={
                "team_id": str(target_team_id),
                "user_id": str(target_user_id),
                "role": role,
            },
            operation=_add,
        )

    except MembershipAlreadyExistsError:
        return fail(
            name="add_team_member",
            description=DESCRIPTION,
            code="MEMBERSHIP_ALREADY_EXISTS",
            message="This user is already a member of the team.",
            status=409,
            inputs=inputs,
        )

    except MembershipRelatedRecordNotFoundError:
        return fail(
            name="add_team_member",
            description=DESCRIPTION,
            code="RELATED_RECORD_NOT_FOUND",
            message="The specified team or user no longer exists.",
            status=404,
            inputs=inputs,
        )

    except InvalidMembershipRecordError:
        return fail(
            name="add_team_member",
            description=DESCRIPTION,
            code="INVALID_MEMBERSHIP_ROLE",
            message="The requested membership role is invalid.",
            status=400,
            inputs=inputs,
        )

    except MembershipDatabaseError:
        logger.exception("Adding a team member failed.")
        return fail(
            name="add_team_member",
            description=DESCRIPTION,
            code="MEMBERSHIP_CREATE_FAILED",
            message="Unable to add the team member right now.",
            status=500,
            inputs=inputs,
        )