"""Central authorization policy for OpsPilot."""

from dataclasses import dataclass, field
from typing import Literal
from uuid import UUID


class AuthenticationRequiredError(Exception):
    """The operation requires an authenticated actor."""


class PermissionDeniedError(Exception):
    """The actor lacks the required permission."""


@dataclass(frozen=True)
class PermissionOverride:
    """A user-specific permission exception."""

    permission: str
    effect: Literal["allow", "deny"]
    team_id: UUID | None = None


@dataclass(frozen=True)
class ActorContext:
    """Identity and authorization data loaded by trusted backend code."""

    user_id: UUID
    permissions: frozenset[str] = field(default_factory=frozenset)
    is_system: bool = False

    # Team-scoped permission grants: (team_id, permission_key).
    team_permissions: frozenset[tuple[UUID, str]] = field(
        default_factory=frozenset
    )

    # Explicit user-specific allow/deny rules.
    permission_overrides: tuple[PermissionOverride, ...] = ()

    # Membership and membership-level roles loaded by trusted code.
    team_ids: frozenset[UUID] = field(default_factory=frozenset)
    team_roles: frozenset[tuple[UUID, str]] = field(
        default_factory=frozenset
    )


def require_authenticated(
    actor: ActorContext | None,
) -> ActorContext:
    """Require an authenticated actor context."""

    if actor is None:
        raise AuthenticationRequiredError(
            "Authentication is required."
        )

    return actor


def has_permission(
    actor: ActorContext,
    permission: str,
    team_id: UUID | None = None,
) -> bool:
    """Resolve a permission using grants and applicable overrides.

    Explicit deny overrides take precedence over all matching grants
    and allow overrides. Team-scoped grants only apply to that team.
    """

    if actor.is_system:
        return True

    applicable_overrides = tuple(
        override
        for override in actor.permission_overrides
        if override.permission == permission
        and (
            override.team_id is None
            or (
                team_id is not None
                and override.team_id == team_id
            )
        )
    )

    # A deny wins if any applicable override denies this permission.
    if any(
        override.effect == "deny"
        for override in applicable_overrides
    ):
        return False

    # An applicable explicit allow grants this permission.
    if any(
        override.effect == "allow"
        for override in applicable_overrides
    ):
        return True

    # System-scoped RBAC permissions.
    if permission in actor.permissions:
        return True

    # Team-scoped permissions require a specific team context.
    if team_id is not None and (
        team_id,
        permission,
    ) in actor.team_permissions:
        return True

    return False


def require_permission(
    actor: ActorContext,
    permission: str,
    team_id: UUID | None = None,
) -> None:
    """Raise when the actor lacks the required permission."""

    if not has_permission(actor, permission, team_id):
        raise PermissionDeniedError(
            "You do not have permission to perform this action."
        )


def has_team_role(
    actor: ActorContext,
    team_id: UUID,
    role: str,
) -> bool:
    """Check a team membership role for the specified team."""

    if actor.is_system:
        return True

    return (
        team_id in actor.team_ids
        and (team_id, role) in actor.team_roles
    )


def can_access_team(
    actor: ActorContext,
    team_id: UUID,
) -> bool:
    """Check whether the actor may access the specified team."""

    if actor.is_system:
        return True

    if team_id in actor.team_ids:
        return True

    return (
        has_permission(actor, "teams:read:any", team_id)
        or has_permission(actor, "teams:list:any", team_id)
        or has_permission(actor, "teams:manage:any", team_id)
    )


def can_read_account(
    actor: ActorContext,
    target_user_id: UUID,
) -> bool:
    """Allow self-access or authorized account-wide access."""

    return (
        actor.is_system
        or actor.user_id == target_user_id
        or has_permission(actor, "accounts:read:any")
    )