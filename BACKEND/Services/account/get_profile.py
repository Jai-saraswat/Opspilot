"""Retrieve the authenticated user's own profile."""

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
)

logger = logging.getLogger(__name__)


def get_profile(*, actor_user_id: str) -> dict[str, Any]:
    name = "get_profile"
    sub = "profile"
    desc = "Retrieve the authenticated user's profile."
    inputs = {"user_id": str(actor_user_id)}

    try:
        user = get_user_by_id(parse_uuid(actor_user_id))

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
            description="Profile retrieved successfully.",
            outputs={"user": to_public_user(user)},
            inputs=inputs,
        )

    except (ValueError, TypeError, AttributeError):
        return fail(
            name=name,
            subcategory=sub,
            description=desc,
            code="INVALID_USER_ID",
            message="Invalid authenticated user ID.",
            status=400,
            inputs=inputs,
        )

    except Exception:
        logger.exception("Profile retrieval failed.")

        return fail(
            name=name,
            subcategory=sub,
            description=desc,
            code="PROFILE_LOOKUP_FAILED",
            message="Unable to retrieve your profile right now.",
            status=500,
            inputs=inputs,
        )