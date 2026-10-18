"""Load database-backed authorization context for OpsPilot."""

from __future__ import annotations

from uuid import UUID

import psycopg

from BACKEND.Postgres.gateway import get_connection
from BACKEND.Postgres.Operations.users.get_user_by_id import (
    get_user_by_id,
)
from BACKEND.Postgres.Operations.authorization.list_user_roles import (
    list_user_roles,
)
from BACKEND.Postgres.Operations.authorization.list_role_permissions import (
    list_role_permissions,
)
from BACKEND.Postgres.Operations.authorization.list_permissions import (
    list_permissions,
)
from BACKEND.Postgres.Operations.authorization.get_user_permission_overrides import (
    get_user_permission_overrides,
)
from BACKEND.Postgres.Operations.memberships.get_membership import (
    get_membership,
)

from BACKEND.Services.authorization.policy import (
    ActorContext,
    AuthenticationRequiredError,
    PermissionOverride,
)


def _parse_uuid(value: UUID | str) -> UUID:
    try:
        return value if isinstance(value, UUID) else UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        raise AuthenticationRequiredError(
            "A valid authenticated actor is required."
        ) from None


def _load_actor_context(
    user_id: UUID,
    team_id: UUID | None,
    connection: psycopg.Connection,
) -> ActorContext:
    """Load authorization data using the caller's database connection."""

    user = get_user_by_id(user_id, connection=connection)

    if not user or user.get("account_status") != "active":
        raise AuthenticationRequiredError(
            "An active authenticated actor is required."
        )

    # Only system roles are unambiguously global in the current schema.
    roles = list_user_roles(
        user_id,
        scope="system",
        connection=connection,
    )

    granted_permissions: set[str] = set()

    for role in roles:
        role_id = _parse_uuid(role["id"])

        for permission in list_role_permissions(
            role_id,
            connection=connection,
        ):
            granted_permissions.add(permission["permission_key"])

    # With a team ID, load global overrides plus overrides for that team.
    # Without one, load all overrides; policy.py will ignore team-specific
    # overrides when evaluating a permission without a team context.
    override_rows = get_user_permission_overrides(
        user_id,
        team_id=team_id,
        connection=connection,
    )

    overrides: list[PermissionOverride] = []

    if override_rows:
        permission_rows = list_permissions(connection=connection)

        permission_keys = {
            str(permission["id"]): permission["permission_key"]
            for permission in permission_rows
        }

        for row in override_rows:
            permission_key = permission_keys.get(
                str(row["permission_id"])
            )

            # Fail closed if stored authorization data cannot be resolved.
            if permission_key is None:
                raise RuntimeError(
                    "A permission override references an unknown permission."
                )

            effect = row["effect"]

            if effect not in {"allow", "deny"}:
                raise RuntimeError(
                    "A permission override has an invalid effect."
                )

            scoped_team_id = (
                _parse_uuid(row["team_id"])
                if row["team_id"] is not None
                else None
            )

            overrides.append(
                PermissionOverride(
                    permission=permission_key,
                    effect=effect,
                    team_id=scoped_team_id,
                )
            )

    team_ids: frozenset[UUID] = frozenset()
    team_roles: frozenset[tuple[UUID, str]] = frozenset()

    if team_id is not None:
        membership = get_membership(
            team_id=team_id,
            user_id=user_id,
            connection=connection,
        )

        if membership is not None:
            team_ids = frozenset({team_id})
            team_roles = frozenset({
                (team_id, membership["role"])
            })

    return ActorContext(
        user_id=user_id,
        permissions=frozenset(granted_permissions),
        is_system=False,
        permission_overrides=tuple(overrides),
        team_ids=team_ids,
        team_roles=team_roles,
        team_permissions=frozenset(),
    )


def load_actor_context(
    user_id: UUID | str,
    *,
    team_id: UUID | str | None = None,
    connection: psycopg.Connection | None = None,
) -> ActorContext:
    """Build an actor context from trusted database records.

    A supplied connection remains owned by the caller. Otherwise,
    this function opens one connection for the authorization reads.
    """

    actor_id = _parse_uuid(user_id)
    parsed_team_id = (
        _parse_uuid(team_id)
        if team_id is not None
        else None
    )

    if connection is not None:
        return _load_actor_context(
            actor_id,
            parsed_team_id,
            connection,
        )

    with get_connection() as conn:
        return _load_actor_context(
            actor_id,
            parsed_team_id,
            conn,
        )