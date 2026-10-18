"""Delete a team when authorization and database constraints permit."""

from __future__ import annotations

import logging
from uuid import UUID

from BACKEND.Postgres.Operations.teams.get_team_by_id import (
    get_team_by_id as get_team_op,
)
from BACKEND.Postgres.Operations.teams.delete_team import (
    delete_team as delete_team_op,
)
from BACKEND.Postgres.Operations.teams.errors import (
    TeamDatabaseError,
    TeamInUseError,
)
from BACKEND.Services.idempotency import execute_idempotently

from ._common import (
    active_actor,
    can_manage_team,
    fail,
    parse_uuid,
    success,
)

logger = logging.getLogger(__name__)

DESCRIPTION = (
    "Delete a team when the actor is authorized and constraints permit it."
)


def delete_team(
    *,
    actor_user_id: UUID | str,
    team_id: UUID | str,
    idempotency_key: str | None = None,
):
    try:
        actor_id = active_actor(actor_user_id)
        target_id = parse_uuid(team_id)
    except (TypeError, ValueError, AttributeError):
        return fail(
            name="delete_team",
            description=DESCRIPTION,
            code="INVALID_TEAM_ID",
            message="A valid team identifier is required.",
            status=400,
        )

    if actor_id is None:
        return fail(
            name="delete_team",
            description=DESCRIPTION,
            code="UNAUTHENTICATED",
            message="An active authenticated account is required.",
            status=401,
        )

    inputs = {"team_id": str(target_id)}

    try:
        def _delete(connection):
            team = get_team_op(
                target_id,
                connection=connection,
            )

            if team is None:
                return fail(
                    name="delete_team",
                    description=DESCRIPTION,
                    code="TEAM_NOT_FOUND",
                    message="The team was not found.",
                    status=404,
                    inputs=inputs,
                )

            if not can_manage_team(
                actor_id,
                target_id,
                "teams:delete:any",
            ):
                return fail(
                    name="delete_team",
                    description=DESCRIPTION,
                    code="FORBIDDEN",
                    message=(
                        "Only a team lead or authorized administrator "
                        "can delete this team."
                    ),
                    status=403,
                    inputs=inputs,
                )

            deleted = delete_team_op(
                target_id,
                connection=connection,
            )

            if not deleted:
                return fail(
                    name="delete_team",
                    description=DESCRIPTION,
                    code="TEAM_NOT_FOUND",
                    message="The team was not found.",
                    status=404,
                    inputs=inputs,
                )

            return success(
                name="delete_team",
                description=DESCRIPTION,
                data={"team_id": str(target_id), "deleted": True},
                inputs=inputs,
            )

        return execute_idempotently(
            user_id=actor_id,
            idempotency_key=idempotency_key,
            operation_name="delete_team",
            category="teams",
            subcategory="team_management",
            description=DESCRIPTION,
            payload={"team_id": str(target_id)},
            operation=_delete,
        )

    except TeamInUseError:
        return fail(
            name="delete_team",
            description=DESCRIPTION,
            code="TEAM_IN_USE",
            message=(
                "This team cannot be deleted while work items "
                "reference it."
            ),
            status=409,
            inputs=inputs,
        )

    except TeamDatabaseError:
        logger.exception("Team deletion failed.")
        return fail(
            name="delete_team",
            description=DESCRIPTION,
            code="TEAM_DELETE_FAILED",
            message="Unable to delete the team right now.",
            status=500,
            inputs=inputs,
        )