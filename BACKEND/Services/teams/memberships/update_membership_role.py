"""Change a user's role within a team."""

from __future__ import annotations

import logging
from uuid import UUID

from BACKEND.Postgres.Operations.teams.get_team_by_id import (
    get_team_by_id as get_team_op,
)
from BACKEND.Postgres.Operations.memberships.get_membership import (
    get_membership as get_membership_op,
)
from BACKEND.Postgres.Operations.memberships.list_team_members import (
    list_team_members as list_members_op,
)
from BACKEND.Postgres.Operations.memberships.update_membership_role import (
    update_membership_role as update_role_op,
)
from BACKEND.Postgres.Operations.memberships.errors import (
    InvalidMembershipRecordError,
    MembershipDatabaseError,
)
from BACKEND.Services.idempotency import execute_idempotently
from BACKEND.Services.teams._common import active_actor, fail, parse_uuid, success

from ._common import (
    can_manage_roles,
    public_membership,
    validate_role,
)

logger = logging.getLogger(__name__)

DESCRIPTION = "Change a user's role within a team."


def update_membership_role(
    *,
    actor_user_id: UUID | str,
    team_id: UUID | str,
    user_id: UUID | str,
    role: str,
    idempotency_key: str | None = None,
):
    try:
        actor_id = active_actor(actor_user_id)
        target_team_id = parse_uuid(team_id)
        target_user_id = parse_uuid(user_id)
    except (TypeError, ValueError, AttributeError):
        return fail(
            name="update_membership_role",
            description=DESCRIPTION,
            code="INVALID_IDENTIFIER",
            message="Valid team and user identifiers are required.",
            status=400,
        )

    if actor_id is None:
        return fail(
            name="update_membership_role",
            description=DESCRIPTION,
            code="UNAUTHENTICATED",
            message="An active authenticated account is required.",
            status=401,
        )

    if not validate_role(role):
        return fail(
            name="update_membership_role",
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
        def _update_role(connection):
            if get_team_op(
                target_team_id,
                connection=connection,
            ) is None:
                return fail(
                    name="update_membership_role",
                    description=DESCRIPTION,
                    code="TEAM_NOT_FOUND",
                    message="The team was not found.",
                    status=404,
                    inputs=inputs,
                )

            existing = get_membership_op(
                team_id=target_team_id,
                user_id=target_user_id,
                connection=connection,
            )

            if existing is None:
                return fail(
                    name="update_membership_role",
                    description=DESCRIPTION,
                    code="MEMBERSHIP_NOT_FOUND",
                    message="The user is not a member of this team.",
                    status=404,
                    inputs=inputs,
                )

            if not can_manage_roles(actor_id, target_team_id):
                return fail(
                    name="update_membership_role",
                    description=DESCRIPTION,
                    code="FORBIDDEN",
                    message=(
                        "Only a team lead or authorized administrator "
                        "can change member roles."
                    ),
                    status=403,
                    inputs=inputs,
                )

            if existing["role"] == role:
                return success(
                    name="update_membership_role",
                    description="The membership already has the requested role.",
                    data={"membership": public_membership(existing)},
                    inputs=inputs,
                )

            # Do not allow a lead to demote themselves if they are the only lead.
            if (
                actor_id == target_user_id
                and existing["role"] == "lead"
                and role != "lead"
            ):
                current_leads = list_members_op(
                    team_id=target_team_id,
                    limit=100,
                    offset=0,
                    role="lead",
                    connection=connection,
                )

                if current_leads["total"] <= 1:
                    return fail(
                        name="update_membership_role",
                        description=DESCRIPTION,
                        code="LAST_LEAD_CANNOT_BE_DEMOTED",
                        message="The team's only lead cannot demote themselves.",
                        status=409,
                        inputs=inputs,
                    )

            updated = update_role_op(
                team_id=target_team_id,
                user_id=target_user_id,
                role=role,
                connection=connection,
            )

            if updated is None:
                return fail(
                    name="update_membership_role",
                    description=DESCRIPTION,
                    code="MEMBERSHIP_NOT_FOUND",
                    message="The membership no longer exists.",
                    status=404,
                    inputs=inputs,
                )

            return success(
                name="update_membership_role",
                description=DESCRIPTION,
                data={"membership": public_membership(updated)},
                inputs=inputs,
            )

        return execute_idempotently(
            user_id=actor_id,
            idempotency_key=idempotency_key,
            operation_name="update_membership_role",
            category="teams",
            subcategory="team_memberships",
            description=DESCRIPTION,
            payload={
                "team_id": str(target_team_id),
                "user_id": str(target_user_id),
                "role": role,
            },
            operation=_update_role,
        )

    except InvalidMembershipRecordError:
        return fail(
            name="update_membership_role",
            description=DESCRIPTION,
            code="INVALID_MEMBERSHIP_ROLE",
            message="The requested membership role is invalid.",
            status=400,
            inputs=inputs,
        )

    except MembershipDatabaseError:
        logger.exception("Membership role update failed.")
        return fail(
            name="update_membership_role",
            description=DESCRIPTION,
            code="MEMBERSHIP_ROLE_UPDATE_FAILED",
            message="Unable to update the membership role right now.",
            status=500,
            inputs=inputs,
        )