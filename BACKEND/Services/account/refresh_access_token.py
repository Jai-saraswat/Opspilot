"""Issue a fresh access token from a valid refresh session."""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from typing import Any

from BACKEND.Postgres.gateway import get_connection
from BACKEND.Postgres.Operations.sessions.get_session_by_token_hash import (
    get_session_by_token_hash,
)
from BACKEND.Postgres.Operations.users.get_user_by_id import (
    get_user_by_id,
)
from BACKEND.Services.account._common import (
    fail,
    success,
    parse_uuid,
    make_access_token,
    access_token_ttl,
)

logger = logging.getLogger(__name__)


def refresh_access_token(
    *,
    refresh_token: str,
) -> dict[str, Any]:
    name = "refresh_access_token"
    sub = "authentication"
    desc = "Issue a new access token from a refresh token."

    if not isinstance(refresh_token, str) or not refresh_token:
        return fail(
            name=name,
            subcategory=sub,
            description=desc,
            code="INVALID_REFRESH_TOKEN",
            message="A valid refresh token is required.",
            status=401,
        )

    try:
        digest = hashlib.sha256(
            refresh_token.encode("utf-8")
        ).hexdigest()

        with get_connection() as connection:
            session = get_session_by_token_hash(
                digest,
                connection=connection,
            )

            if (
                not session
                or session["revoked_at"] is not None
                or session["expires_at"] <= datetime.now(timezone.utc)
            ):
                return fail(
                    name=name,
                    subcategory=sub,
                    description=desc,
                    code="INVALID_REFRESH_TOKEN",
                    message="Refresh token is invalid or expired.",
                    status=401,
                )

            user = get_user_by_id(
                parse_uuid(session["user_id"]),
                connection=connection,
            )

            if not user or user["account_status"] != "active":
                return fail(
                    name=name,
                    subcategory=sub,
                    description=desc,
                    code="ACCOUNT_INACTIVE",
                    message="This account cannot refresh tokens.",
                    status=403,
                )

            token = make_access_token(user["id"])

        return success(
            name=name,
            subcategory=sub,
            description="Access token refreshed successfully.",
            outputs={
                "access_token": token,
                "token_type": "Bearer",
                "expires_in": access_token_ttl(),
            },
        )

    except Exception:
        logger.exception("Access-token refresh failed.")

        return fail(
            name=name,
            subcategory=sub,
            description=desc,
            code="TOKEN_REFRESH_FAILED",
            message="Unable to refresh the access token right now.",
            status=500,
        )