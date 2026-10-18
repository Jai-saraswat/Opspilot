"""Get an account status; self-access or accounts:read:any required."""

from __future__ import annotations

import logging
from typing import Any

from BACKEND.Postgres.Operations.users.get_user_by_id import (
    get_user_by_id,
)
from BACKEND.Services.account._common import (
    fail,
    success,
    parse_uuid,
    actor_has_permission,
)

logger = logging.getLogger(__name__)


def get_account_status(
    *,
    actor_user_id: str,
    target_user_id: str | None = None,
) -> dict[str, Any]:
    name = "get_account_status"
    sub = "account_status"
    desc = "Retrieve account status."

    target_user_id = target_user_id or str(actor_user_id)
    inputs = {"target_user_id": str(target_user_id)}

    try:
        actor_id = parse_uuid(actor_user_id)
        target_id = parse_uuid(target_user_id)

        if (
            actor_id != target_id
            and not actor_has_permission(
                actor_id,
                "accounts:read:any",
            )
        ):
            return fail(
                name=name,
                subcategory=sub,
                description=desc,
                code="FORBIDDEN",
                message="You are not allowed to view this account status.",
                status=403,
                inputs=inputs,
            )

        user = get_user_by_id(target_id)

        if not user:
            return fail(
                name=name,
                subcategory=sub,
                description=desc,
                code="ACCOUNT_NOT_FOUND",
                message="Account not found.",
                status=404,
                inputs=inputs,
            )

        return success(
            name=name,
            subcategory=sub,
            description="Account status retrieved successfully.",
            outputs={
                "user_id": str(user["id"]),
                "account_status": user["account_status"],
            },
            inputs=inputs,
        )

    except (ValueError, TypeError, AttributeError):
        return fail(
            name=name,
            subcategory=sub,
            description=desc,
            code="INVALID_USER_ID",
            message="Invalid user ID.",
            status=400,
            inputs=inputs,
        )

    except Exception:
        logger.exception("Account status lookup failed.")

        return fail(
            name=name,
            subcategory=sub,
            description=desc,
            code="ACCOUNT_STATUS_LOOKUP_FAILED",
            message="Unable to retrieve account status right now.",
            status=500,
            inputs=inputs,
        )