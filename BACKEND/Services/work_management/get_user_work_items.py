"""List a user's assigned work items within their authorized scope."""

from __future__ import annotations

from uuid import UUID

from BACKEND.Postgres.Operations.memberships.errors import MembershipDatabaseError
from BACKEND.Postgres.Operations.memberships.list_user_teams import (
    list_user_teams,
)
from BACKEND.Postgres.Operations.users.get_user_by_id import get_user_by_id
from BACKEND.Postgres.Operations.work_items.errors import WorkItemDatabaseError
from BACKEND.Postgres.Operations.work_items.list_work_items import (
    list_work_items as list_work_items_operation,
)
from BACKEND.Services.work_management._common import (
    active_actor,
    fail,
    has_permission,
    parse_identifier,
    public_work_items,
    success,
    valid_pagination,
)
from BACKEND.Services.work_management.list_work_items import (
    VALID_PRIORITIES,
    VALID_STATUSES,
    VALID_TYPES,
)


def _get_user_team_ids(user_id: UUID) -> list[UUID]:
    """Return all current team IDs using the existing paginated Operation."""
    team_ids: list[UUID] = []
    page_size = 100
    offset = 0

    while True:
        page = list_user_teams(
            user_id=user_id,
            limit=page_size,
            offset=offset,
        )
        rows = page["items"]
        total = page["total"]

        team_ids.extend(parse_identifier(row["id"]) for row in rows)

        offset += len(rows)
        if not rows or offset >= total:
            break

    return list(dict.fromkeys(team_ids))


def _query_team_items(
    *,
    team_id: UUID,
    assignee_id: UUID,
    needed: int,
    status: str | None,
    priority: str | None,
    type: str | None,
    search: str | None,
) -> tuple[list[dict], int]:
    """Fetch at most `needed` records from one team in bounded pages."""
    accumulated: list[dict] = []
    total = 0
    page_size = min(100, max(1, needed))
    offset = 0

    while True:
        page = list_work_items_operation(
            team_id=team_id,
            assignee_id=assignee_id,
            status=status,
            priority=priority,
            type=type,
            search=search,
            limit=page_size,
            offset=offset,
        )

        total = page["total"]
        rows = page["items"]
        accumulated.extend(rows)
        offset += len(rows)

        if not rows or offset >= total or offset >= needed:
            break

        page_size = min(100, needed - offset)

    return accumulated, total


def get_user_work_items(
    *,
    actor_user_id: UUID | str,
    user_id: UUID | str | None = None,
    team_id: UUID | str | None = None,
    limit: int = 50,
    offset: int = 0,
    status: str | None = None,
    priority: str | None = None,
    type: str | None = None,
    search: str | None = None,
):
    name = "get_user_work_items"
    inputs = {
        "user_id": str(user_id) if user_id is not None else "self",
        "team_id": str(team_id) if team_id is not None else None,
        "limit": limit,
        "offset": offset,
    }

    actor_id = active_actor(actor_user_id)
    if actor_id is None:
        return fail(
            name=name,
            description="List a user's assigned work items.",
            code="UNAUTHENTICATED",
            message="An active user account is required.",
            status=401,
            inputs=inputs,
        )

    if not valid_pagination(limit, offset):
        return fail(
            name=name,
            description="List a user's assigned work items.",
            code="INVALID_PAGINATION",
            message="Limit must be 1–100 and offset must be non-negative.",
            status=400,
            inputs=inputs,
        )

    if status is not None and status not in VALID_STATUSES:
        return fail(
            name=name,
            description="List a user's assigned work items.",
            code="INVALID_STATUS",
            message="The status filter is invalid.",
            status=400,
            inputs=inputs,
        )

    if priority is not None and priority not in VALID_PRIORITIES:
        return fail(
            name=name,
            description="List a user's assigned work items.",
            code="INVALID_PRIORITY",
            message="The priority filter is invalid.",
            status=400,
            inputs=inputs,
        )

    if type is not None and type not in VALID_TYPES:
        return fail(
            name=name,
            description="List a user's assigned work items.",
            code="INVALID_TYPE",
            message="The type filter is invalid.",
            status=400,
            inputs=inputs,
        )

    try:
        target_id = (
            parse_identifier(user_id)
            if user_id is not None
            else actor_id
        )
        resolved_team_id = (
            parse_identifier(team_id)
            if team_id is not None
            else None
        )
    except (ValueError, TypeError, AttributeError):
        return fail(
            name=name,
            description="List a user's assigned work items.",
            code="INVALID_IDENTIFIER",
            message="The user or team identifier is invalid.",
            status=400,
            inputs=inputs,
        )

    try:
        target = get_user_by_id(target_id)

        if target is None or target.get("account_status") != "active":
            return fail(
                name=name,
                description="List a user's assigned work items.",
                code="USER_NOT_FOUND",
                message="The requested active user was not found.",
                status=404,
                inputs=inputs,
            )

        is_self = target_id == actor_id
        globally_authorized = has_permission(
            actor_id,
            "work_items:read:any",
            "work_items:list:any",
            "work_items:manage:any",
        )

        if not is_self and not globally_authorized:
            return fail(
                name=name,
                description="List a user's assigned work items.",
                code="FORBIDDEN",
                message="You cannot inspect another user's assignments.",
                status=403,
                inputs=inputs,
            )

        if resolved_team_id is not None:
            if not is_self and not globally_authorized:
                return fail(
                    name=name,
                    description="List a user's assigned work items.",
                    code="FORBIDDEN",
                    message="You cannot inspect another user's assignments.",
                    status=403,
                    inputs=inputs,
                )

            # The general list Service will verify viewer access to the
            # team. It is safe to filter the target assignee separately.
            from BACKEND.Services.work_management._common import can_view_team

            if not can_view_team(actor_id, resolved_team_id):
                return fail(
                    name=name,
                    description="List a user's assigned work items.",
                    code="FORBIDDEN",
                    message="You cannot view work items for this team.",
                    status=403,
                    inputs=inputs,
                )

            page = list_work_items_operation(
                team_id=resolved_team_id,
                assignee_id=target_id,
                status=status,
                priority=priority,
                type=type,
                search=search,
                limit=limit,
                offset=offset,
            )

            return success(
                name=name,
                description="User work items listed.",
                data={
                    "items": public_work_items(page["items"]),
                    "total": page["total"],
                    "limit": limit,
                    "offset": offset,
                },
                inputs=inputs,
            )

        if not is_self:
            # A system-authorized reader may see the user's assignments
            # across teams without a team filter.
            page = list_work_items_operation(
                assignee_id=target_id,
                status=status,
                priority=priority,
                type=type,
                search=search,
                limit=limit,
                offset=offset,
            )

            return success(
                name=name,
                description="User work items listed.",
                data={
                    "items": public_work_items(page["items"]),
                    "total": page["total"],
                    "limit": limit,
                    "offset": offset,
                },
                inputs=inputs,
            )

        team_ids = _get_user_team_ids(target_id)

        all_items: list[dict] = []
        total = 0
        needed = offset + limit

        for member_team_id in team_ids:
            rows, team_total = _query_team_items(
                team_id=member_team_id,
                assignee_id=target_id,
                needed=needed,
                status=status,
                priority=priority,
                type=type,
                search=search,
            )
            total += team_total
            all_items.extend(rows)

        # Each underlying Operation uses updated_at DESC, id ASC ordering.
        all_items.sort(key=lambda row: str(row["id"]))
        all_items.sort(
            key=lambda row: row["updated_at"],
            reverse=True,
        )

        selected = all_items[offset:offset + limit]

        return success(
            name=name,
            description="User work items listed.",
            data={
                "items": public_work_items(selected),
                "total": total,
                "limit": limit,
                "offset": offset,
            },
            inputs=inputs,
        )

    except MembershipDatabaseError:
        return fail(
            name=name,
            description="List a user's assigned work items.",
            code="DATABASE_ERROR",
            message="The user's team memberships could not be retrieved.",
            status=500,
            inputs=inputs,
        )
    except WorkItemDatabaseError:
        return fail(
            name=name,
            description="List a user's assigned work items.",
            code="DATABASE_ERROR",
            message="The user's work items could not be retrieved.",
            status=500,
            inputs=inputs,
        )