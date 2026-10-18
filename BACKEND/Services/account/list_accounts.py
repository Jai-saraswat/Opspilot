"""List/search accounts with global or team-scoped authorization."""

from __future__ import annotations

import logging
from typing import Any

from BACKEND.Postgres.Operations.users.list_users import (
    list_users as list_users_op,
)
from BACKEND.Services.account._common import (
    actor_has_permission,
    actor_is_active,
    fail,
    parse_uuid,
    success,
    to_public_user,
)
from BACKEND.Services.teams.memberships._common import (
    can_manage_members,
)

logger = logging.getLogger(__name__)

_VALID_STATUSES = {"active", "suspended", "deactivated"}

# Fields exposed to team leads when searching for member candidates.
_CANDIDATE_FIELDS = {
    "id",
    "full_name",
    "email",
    "account_status",
}


def list_accounts(
    *,
    actor_user_id: str,
    limit: int = 50,
    offset: int = 0,
    account_status: str | None = None,
    search: str | None = None,
    team_id: str | None = None,
) -> dict[str, Any]:
    """List accounts or search active member candidates for a team.

    Global account listing requires accounts:list.

    Team-scoped candidate search is permitted to users who can manage
    membership in the specified team. Those requests are restricted to
    active accounts and require a search term.
    """
    name = "list_accounts"
    sub = "account_list"
    desc = "List and search user accounts."

    inputs = {
        "limit": limit,
        "offset": offset,
        "account_status": account_status,
        "search": search,
        "team_id": team_id,
    }

    try:
        # Validate the authenticated actor.
        try:
            actor_id = parse_uuid(actor_user_id)
        except (TypeError, ValueError, AttributeError):
            return fail(
                name=name,
                subcategory=sub,
                description=desc,
                code="UNAUTHENTICATED",
                message="A valid authenticated account is required.",
                status=401,
                inputs=inputs,
            )

        if not actor_is_active(actor_id):
            return fail(
                name=name,
                subcategory=sub,
                description=desc,
                code="UNAUTHENTICATED",
                message="An active account is required.",
                status=401,
                inputs=inputs,
            )

        # Preserve the existing system-level permission.
        has_global_access = actor_has_permission(
            actor_id,
            "accounts:list",
        )

        target_team_id = None

        if team_id is not None:
            try:
                target_team_id = parse_uuid(team_id)
            except (TypeError, ValueError, AttributeError):
                return fail(
                    name=name,
                    subcategory=sub,
                    description=desc,
                    code="INVALID_TEAM_ID",
                    message="A valid team ID is required.",
                    status=400,
                    inputs=inputs,
                )

        # Team leads without global account-list permission can only
        # perform candidate searches for teams they can manage.
        if not has_global_access:
            if (
                target_team_id is None
                or not can_manage_members(
                    actor_id,
                    target_team_id,
                )
            ):
                return fail(
                    name=name,
                    subcategory=sub,
                    description=desc,
                    code="FORBIDDEN",
                    message=(
                        "You are not allowed to list accounts "
                        "for this request."
                    ),
                    status=403,
                    inputs=inputs,
                )

            # Candidate searches must never reveal suspended or
            # deactivated accounts.
            if account_status not in (None, "active"):
                return fail(
                    name=name,
                    subcategory=sub,
                    description=desc,
                    code="INVALID_STATUS",
                    message=(
                        "Team-scoped searches are restricted "
                        "to active accounts."
                    ),
                    status=400,
                    inputs=inputs,
                )

            # Require a meaningful search term so a team lead cannot
            # enumerate the entire account directory.
            if (
                not isinstance(search, str)
                or len(search.strip()) < 2
            ):
                return fail(
                    name=name,
                    subcategory=sub,
                    description=desc,
                    code="INVALID_SEARCH",
                    message=(
                        "Enter at least two characters to search "
                        "active account candidates."
                    ),
                    status=400,
                    inputs=inputs,
                )

            account_status = "active"

        # Preserve existing account-list validation.
        if (
            account_status is not None
            and account_status not in _VALID_STATUSES
        ):
            return fail(
                name=name,
                subcategory=sub,
                description=desc,
                code="INVALID_STATUS",
                message="Unsupported account status filter.",
                status=400,
                inputs=inputs,
            )

        if search is not None and not isinstance(search, str):
            return fail(
                name=name,
                subcategory=sub,
                description=desc,
                code="INVALID_SEARCH",
                message="Search must be text.",
                status=400,
                inputs=inputs,
            )

        result = list_users_op(
            limit=limit,
            offset=offset,
            account_status=account_status,
            search=search.strip() if search else None,
        )

        # Keep the existing public account representation.
        public_users = [
            to_public_user(user)
            for user in result["items"]
        ]

        if not has_global_access:
            # Return only the fields needed for choosing a candidate.
            public_users = [
                {
                    key: user[key]
                    for key in _CANDIDATE_FIELDS
                    if key in user
                }
                for user in public_users
            ]

        result["items"] = public_users

        return success(
            name=name,
            subcategory=sub,
            description="Accounts retrieved successfully.",
            outputs=result,
            inputs=inputs,
        )

    except ValueError as exc:
        return fail(
            name=name,
            subcategory=sub,
            description=desc,
            code="INVALID_PAGINATION",
            message=str(exc),
            status=400,
            inputs=inputs,
        )

    except Exception:
        logger.exception("Account listing failed.")

        return fail(
            name=name,
            subcategory=sub,
            description=desc,
            code="ACCOUNT_LIST_FAILED",
            message="Unable to retrieve accounts right now.",
            status=500,
            inputs=inputs,
        )