"""Revoke the current refresh-token session."""

from __future__ import annotations

import hashlib
import logging
from typing import Any

from BACKEND.Postgres.gateway import get_connection
from BACKEND.Postgres.Operations.sessions.get_session_by_token_hash import (
    get_session_by_token_hash,
)
from BACKEND.Postgres.Operations.sessions.revoke_session import (
    revoke_session,
)
from BACKEND.Services.account._common import (
    fail,
    success,
    parse_uuid,
)

logger = logging.getLogger(__name__)


def logout_user(
    *,
    user_id: str,
    refresh_token: str,
) -> dict[str, Any]:
    name = "logout_user"
    sub = "authentication"
    desc = "Revoke the current login session."
    inputs = {"user_id": str(user_id)}

    if not isinstance(refresh_token, str) or not refresh_token:
        return fail(
            name=name,
            subcategory=sub,
            description=desc,
            code="REFRESH_TOKEN_REQUIRED",
            message="Refresh token is required.",
            status=400,
            inputs=inputs,
        )

    try:
        actor_id = parse_uuid(user_id)

        token_hash = hashlib.sha256(
            refresh_token.encode("utf-8")
        ).hexdigest()

        with get_connection() as connection:
            session = get_session_by_token_hash(
                token_hash,
                connection=connection,
            )

            # Return the same result for an unknown token or another user's
            # token to avoid exposing session information.
            if session and session["user_id"] == actor_id:
                revoke_session(
                    session["id"],
                    connection=connection,
                )

        return success(
            name=name,
            subcategory=sub,
            description="Logout completed.",
            outputs={"logged_out": True},
            inputs=inputs,
        )

    except Exception:
        logger.exception("Logout failed.")

        return fail(
            name=name,
            subcategory=sub,
            description=desc,
            code="LOGOUT_FAILED",
            message="Unable to log out right now.",
            status=500,
            inputs=inputs,
        )