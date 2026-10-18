"""Remove a team member without leaving the team without a lead."""

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
from BACKEND.Postgres.Operations.memberships.remove_team_member import (
    remove_team_member as remove_member_op,
)
from BACKEND.Postgres.Operations.memberships.errors import MembershipDatabaseError
from BACKEND.Services.idempotency import execute_idempotently
from BACKEND.Services.teams._common import active_actor, fail, parse_uuid, success

from ._common import can_manage_members

logger = logging.getLogger(__name__)

DESCRIPTION = (
    "Remove a user from a team without leaving the team without a lead."
)


def remove_team_member(
    *,
    actor_user_id: UUID | str,
    team_id: UUID | str,
    user_id: UUID | str,
    idempotency_key: str | None = None,
):
    try:
        actor_id = active_actor(actor_user_id)
        target_team_id = parse_uuid(team_id)
        target_user_id = parse_uuid(user_id)
    except (TypeError, ValueError, AttributeError):
        return fail(
            name="remove_team_member",
            description=DESCRIPTION,
            code="INVALID_IDENTIFIER",
            message="Valid team and user identifiers are required.",
            status=400,
        )

    if actor_id is None:
        return fail(
            name="remove_team_member",
            description=DESCRIPTION,
            code="UNAUTHENTICATED",
            message="An active authenticated account is required.",
            status=401,
        )

    inputs = {
        "team_id": str(target_team_id),
        "user_id": str(target_user_id),
    }

    try:
        def _remove(connection):
            if get_team_op(
                target_team_id,
                connection=connection,
            ) is None:
                return fail(
                    name="remove_team_member",
                    description=DESCRIPTION,
                    code="TEAM_NOT_FOUND",
                    message="The team was not found.",
                    status=404,
                    inputs=inputs,
                )

            membership = get_membership_op(
                team_id=target_team_id,
                user_id=target_user_id,
                connection=connection,
            )

            if membership is None:
                return fail(
                    name="remove_team_member",
                    description=DESCRIPTION,
                    code="MEMBERSHIP_NOT_FOUND",
                    message="The user is not a member of this team.",
                    status=404,
                    inputs=inputs,
                )

            if not can_manage_members(actor_id, target_team_id):
                return fail(
                    name="remove_team_member",
                    description=DESCRIPTION,
                    code="FORBIDDEN",
                    message=(
                        "Only a team lead or authorized administrator "
                        "can remove members."
                    ),
                    status=403,
                    inputs=inputs,
                )

            if membership["role"] == "lead":
                leads = list_members_op(
                    team_id=target_team_id,
                    limit=100,
                    offset=0,
                    role="lead",
                    connection=connection,
                )

                if leads["total"] <= 1:
                    return fail(
                        name="remove_team_member",
                        description=DESCRIPTION,
                        code="LAST_LEAD_CANNOT_BE_REMOVED",
                        message=(
                            "Promote another member to lead before "
                            "removing the current lead."
                        ),
                        status=409,
                        inputs=inputs,
                    )

            removed = remove_member_op(
                team_id=target_team_id,
                user_id=target_user_id,
                connection=connection,
            )

            if not removed:
                return fail(
                    name="remove_team_member",
                    description=DESCRIPTION,
                    code="MEMBERSHIP_NOT_FOUND",
                    message="The membership no longer exists.",
                    status=404,
                    inputs=inputs,
                )

            return success(
                name="remove_team_member",
                description=DESCRIPTION,
                data={
                    "team_id": str(target_team_id),
                    "user_id": str(target_user_id),
                    "removed": True,
                },
                inputs=inputs,
            )

        return execute_idempotently(
            user_id=actor_id,
            idempotency_key=idempotency_key,
            operation_name="remove_team_member",
            category="teams",
            subcategory="team_memberships",
            description=DESCRIPTION,
            payload={
                "team_id": str(target_team_id),
                "user_id": str(target_user_id),
            },
            operation=_remove,
        )

    except MembershipDatabaseError:
        logger.exception("Removing a team member failed.")
        return fail(
            name="remove_team_member",
            description=DESCRIPTION,
            code="MEMBERSHIP_REMOVE_FAILED",
            message="Unable to remove the team member right now.",
            status=500,
            inputs=inputs,
        )