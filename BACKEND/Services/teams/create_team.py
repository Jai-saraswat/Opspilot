"""Create a team and its creator's lead membership atomically."""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from BACKEND.Postgres.Operations.teams.create_team import (
    create_team as create_team_op,
)
from BACKEND.Postgres.Operations.teams.errors import (
    InvalidTeamRecordError,
    TeamAlreadyExistsError,
    TeamCreatorNotFoundError,
    TeamDatabaseError,
)
from BACKEND.Postgres.Operations.memberships.add_team_member import (
    add_team_member,
)
from BACKEND.Postgres.Operations.memberships.errors import (
    InvalidMembershipRecordError,
    MembershipAlreadyExistsError,
    MembershipDatabaseError,
    MembershipRelatedRecordNotFoundError,
)
from BACKEND.Services.idempotency import execute_idempotently

from ._common import (
    active_actor,
    active_user_exists,
    fail,
    public_team,
    public_membership,
    success,
    valid_team_name,
)

logger = logging.getLogger(__name__)

DESCRIPTION = "Create a team and establish its creator as team lead."


def create_team(
    *,
    actor_user_id: UUID | str,
    name: str,
    description: str | None = None,
    idempotency_key: str | None = None,
):
    inputs = {"name": name, "description": description}
    actor_id = active_actor(actor_user_id)

    if actor_id is None:
        return fail(
            name="create_team",
            description=DESCRIPTION,
            code="UNAUTHENTICATED",
            message="An active authenticated account is required.",
            status=401,
            inputs=inputs,
        )

    if not valid_team_name(name):
        return fail(
            name="create_team",
            description=DESCRIPTION,
            code="INVALID_TEAM_NAME",
            message="Team name must contain 1–100 non-whitespace characters.",
            status=400,
            inputs=inputs,
        )

    if description is not None and not isinstance(description, str):
        return fail(
            name="create_team",
            description=DESCRIPTION,
            code="INVALID_DESCRIPTION",
            message="Description must be text or null.",
            status=400,
            inputs=inputs,
        )

    if not active_user_exists(actor_id):
        return fail(
            name="create_team",
            description=DESCRIPTION,
            code="ACCOUNT_NOT_FOUND",
            message="The active creator account could not be found.",
            status=401,
            inputs=inputs,
        )

    normalized_name = name.strip()

    try:
        def _create(connection):
            team = create_team_op(
                name=normalized_name,
                description=description,
                created_by=actor_id,
                connection=connection,
            )

            membership = add_team_member(
                team_id=team["id"],
                user_id=actor_id,
                role="lead",
                connection=connection,
            )

            return success(
                name="create_team",
                description=DESCRIPTION,
                data={
                    "team": public_team(team),
                    "membership": public_membership(membership),
                },
                inputs=inputs,
                status=201,
            )

        return execute_idempotently(
            user_id=actor_id,
            idempotency_key=idempotency_key,
            operation_name="create_team",
            category="teams",
            subcategory="team_management",
            description=DESCRIPTION,
            payload={
                "name": normalized_name,
                "description": description,
            },
            operation=_create,
        )

    except TeamAlreadyExistsError:
        return fail(
            name="create_team",
            description=DESCRIPTION,
            code="TEAM_NAME_ALREADY_EXISTS",
            message="A team with this name already exists.",
            status=409,
            inputs=inputs,
        )

    except (InvalidTeamRecordError, InvalidMembershipRecordError):
        return fail(
            name="create_team",
            description=DESCRIPTION,
            code="INVALID_TEAM_DATA",
            message="The supplied team data is invalid.",
            status=400,
            inputs=inputs,
        )

    except (
        TeamCreatorNotFoundError,
        MembershipRelatedRecordNotFoundError,
    ):
        return fail(
            name="create_team",
            description=DESCRIPTION,
            code="RELATED_RECORD_NOT_FOUND",
            message=(
                "The creator or a required related record no longer exists."
            ),
            status=404,
            inputs=inputs,
        )

    except (
        TeamDatabaseError,
        MembershipDatabaseError,
        MembershipAlreadyExistsError,
    ):
        logger.exception("Team creation failed.")
        return fail(
            name="create_team",
            description=DESCRIPTION,
            code="TEAM_CREATION_FAILED",
            message="Unable to create the team right now.",
            status=500,
            inputs=inputs,
        )

    except Exception:
        logger.exception("Unexpected team creation failure.")
        return fail(
            name="create_team",
            description=DESCRIPTION,
            code="TEAM_CREATION_FAILED",
            message="Unable to create the team right now.",
            status=500,
            inputs=inputs,
        )