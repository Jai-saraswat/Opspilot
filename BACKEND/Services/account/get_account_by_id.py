"""Get an account by UUID; self-access or accounts:read:any required."""

from __future__ import annotations

import logging
from typing import Any

from BACKEND.Postgres.Operations.users.get_user_by_id import (
    get_user_by_id,
)
from BACKEND.Services.account._common import (
    fail,
    success,
    to_public_user,
    parse_uuid,
    actor_has_permission,
)

logger = logging.getLogger(__name__)


def get_account_by_id(
    *,
    actor_user_id: str,
    target_user_id: str,
) -> dict[str, Any]:
    name = "get_account_by_id"
    sub = "account_read"
    desc = "Retrieve an account by ID."
    inputs = {"target_user_id": str(target_user_id)}

    try:
        actor_id = parse_uuid(actor_user_id)
        target_id = parse_uuid(target_user_id)

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

        if (
            target_id != actor_id
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
                message="You are not allowed to view this account.",
                status=403,
                inputs=inputs,
            )

        return success(
            name=name,
            subcategory=sub,
            description="Account retrieved successfully.",
            outputs={"user": to_public_user(user)},
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
        logger.exception("Account lookup by ID failed.")

        return fail(
            name=name,
            subcategory=sub,
            description=desc,
            code="ACCOUNT_LOOKUP_FAILED",
            message="Unable to retrieve the account right now.",
            status=500,
            inputs=inputs,
        )