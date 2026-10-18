"""Update team details while enforcing team-level authorization."""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from BACKEND.Postgres.Operations.teams.get_team_by_id import (
    get_team_by_id as get_team_op,
)
from BACKEND.Postgres.Operations.teams.update_team import (
    update_team as update_team_op,
    UNSET,
)
from BACKEND.Postgres.Operations.teams.errors import (
    InvalidTeamRecordError,
    TeamAlreadyExistsError,
    TeamDatabaseError,
)
from BACKEND.Services.idempotency import execute_idempotently

from ._common import (
    active_actor,
    can_manage_team,
    fail,
    parse_uuid,
    public_team,
    success,
    valid_team_name,
)

logger = logging.getLogger(__name__)

DESCRIPTION = "Update a team's name or description."


def update_team(
    *,
    actor_user_id: UUID | str,
    team_id: UUID | str,
    name: str | None = None,
    description: str | None | Any = UNSET,
    idempotency_key: str | None = None,
):
    try:
        actor_id = active_actor(actor_user_id)
        target_id = parse_uuid(team_id)
    except (TypeError, ValueError, AttributeError):
        return fail(
            name="update_team",
            description=DESCRIPTION,
            code="INVALID_TEAM_ID",
            message="A valid team identifier is required.",
            status=400,
        )

    if actor_id is None:
        return fail(
            name="update_team",
            description=DESCRIPTION,
            code="UNAUTHENTICATED",
            message="An active authenticated account is required.",
            status=401,
        )

    if name is not None and not valid_team_name(name):
        return fail(
            name="update_team",
            description=DESCRIPTION,
            code="INVALID_TEAM_NAME",
            message="Team name must contain 1–100 non-whitespace characters.",
            status=400,
        )

    if (
        description is not UNSET
        and description is not None
        and not isinstance(description, str)
    ):
        return fail(
            name="update_team",
            description=DESCRIPTION,
            code="INVALID_DESCRIPTION",
            message="Description must be text or null.",
            status=400,
        )

    if name is None and description is UNSET:
        return fail(
            name="update_team",
            description=DESCRIPTION,
            code="EMPTY_UPDATE",
            message="Provide a team name or description to update.",
            status=400,
        )

    normalized_name = name.strip() if name is not None else None

    inputs = {
        "team_id": str(target_id),
        "name": normalized_name,
        "description": (
            None if description is None
            else "<unchanged>" if description is UNSET
            else description
        ),
    }

    try:
        def _update(connection):
            current = get_team_op(
                target_id,
                connection=connection,
            )

            if current is None:
                return fail(
                    name="update_team",
                    description=DESCRIPTION,
                    code="TEAM_NOT_FOUND",
                    message="The team was not found.",
                    status=404,
                    inputs=inputs,
                )

            if not can_manage_team(
                actor_id,
                target_id,
                "teams:update:any",
            ):
                return fail(
                    name="update_team",
                    description=DESCRIPTION,
                    code="FORBIDDEN",
                    message=(
                        "Only a team lead or authorized administrator "
                        "can update this team."
                    ),
                    status=403,
                    inputs=inputs,
                )

            kwargs: dict[str, Any] = {}

            if normalized_name is not None:
                kwargs["name"] = normalized_name

            if description is not UNSET:
                kwargs["description"] = description

            updated = update_team_op(
                target_id,
                **kwargs,
                connection=connection,
            )

            if updated is None:
                return fail(
                    name="update_team",
                    description=DESCRIPTION,
                    code="TEAM_NOT_FOUND",
                    message="The team no longer exists.",
                    status=404,
                    inputs=inputs,
                )

            return success(
                name="update_team",
                description=DESCRIPTION,
                data={"team": public_team(updated)},
                inputs=inputs,
            )

        return execute_idempotently(
            user_id=actor_id,
            idempotency_key=idempotency_key,
            operation_name="update_team",
            category="teams",
            subcategory="team_management",
            description=DESCRIPTION,
            payload={
                "team_id": str(target_id),
                "name": normalized_name,
                "description_supplied": description is not UNSET,
                "description": (
                    None if description is UNSET else description
                ),
            },
            operation=_update,
        )

    except TeamAlreadyExistsError:
        return fail(
            name="update_team",
            description=DESCRIPTION,
            code="TEAM_NAME_ALREADY_EXISTS",
            message="A team with this name already exists.",
            status=409,
            inputs=inputs,
        )

    except InvalidTeamRecordError:
        return fail(
            name="update_team",
            description=DESCRIPTION,
            code="INVALID_TEAM_DATA",
            message="The supplied team data is invalid.",
            status=400,
            inputs=inputs,
        )

    except TeamDatabaseError:
        logger.exception("Team update failed.")
        return fail(
            name="update_team",
            description=DESCRIPTION,
            code="TEAM_UPDATE_FAILED",
            message="Unable to update the team right now.",
            status=500,
            inputs=inputs,
        )