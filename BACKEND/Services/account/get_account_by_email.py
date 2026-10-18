"""Get an account by email; self-access or accounts:read:any required."""

from __future__ import annotations

import logging
from typing import Any

from BACKEND.Postgres.Operations.users.get_user_by_email import (
    get_user_by_email,
)
from BACKEND.Services.account._common import (
    fail,
    success,
    to_public_user,
    parse_uuid,
    actor_has_permission,
)

logger = logging.getLogger(__name__)


def get_account_by_email(
    *,
    actor_user_id: str,
    email: str,
) -> dict[str, Any]:
    name = "get_account_by_email"
    sub = "account_read"
    desc = "Retrieve an account by email address."
    inputs = {
        "email": email if isinstance(email, str) else "",
    }

    try:
        actor_id = parse_uuid(actor_user_id)

        if not isinstance(email, str) or not email.strip():
            return fail(
                name=name,
                subcategory=sub,
                description=desc,
                code="INVALID_EMAIL",
                message="A valid email address is required.",
                status=400,
                inputs=inputs,
            )

        normalized = email.strip().casefold()
        user = get_user_by_email(normalized)

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
            user["id"] != actor_id
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

    except Exception:
        logger.exception("Account lookup by email failed.")

        return fail(
            name=name,
            subcategory=sub,
            description=desc,
            code="ACCOUNT_LOOKUP_FAILED",
            message="Unable to retrieve the account right now.",
            status=500,
            inputs=inputs,
        )