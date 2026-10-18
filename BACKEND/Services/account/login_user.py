"""Verify credentials and issue access/refresh tokens."""

from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import datetime, timezone, timedelta
from typing import Any

from pwdlib import PasswordHash

from BACKEND.Postgres.gateway import get_connection
from BACKEND.Postgres.Operations.users.get_user_auth_record_by_email import (
    get_user_auth_record_by_email,
)
from BACKEND.Postgres.Operations.sessions.create_session import (
    create_session,
)
from BACKEND.Services.account._common import (
    fail,
    success,
    to_public_user,
    make_access_token,
    access_token_ttl,
)

logger = logging.getLogger(__name__)
_hasher = PasswordHash.recommended()
_REFRESH_TTL_DAYS = 30


def login_user(*, email: str, password: str) -> dict[str, Any]:
    name = "login_user"
    sub = "authentication"
    desc = "Authenticate a user and create a login session."

    safe_inputs = {
        "email": email.strip().casefold()
        if isinstance(email, str)
        else ""
    }

    if (
        not isinstance(email, str)
        or not email.strip()
        or not isinstance(password, str)
        or not password
    ):
        return fail(
            name=name,
            subcategory=sub,
            description=desc,
            code="INVALID_CREDENTIALS",
            message="Email or password is incorrect.",
            status=401,
            inputs=safe_inputs,
        )

    try:
        user = get_user_auth_record_by_email(safe_inputs["email"])

        if not user:
            return fail(
                name=name,
                subcategory=sub,
                description=desc,
                code="INVALID_CREDENTIALS",
                message="Email or password is incorrect.",
                status=401,
                inputs=safe_inputs,
            )

        if user["account_status"] != "active":
            return fail(
                name=name,
                subcategory=sub,
                description=desc,
                code="ACCOUNT_INACTIVE",
                message="This account is not active.",
                status=403,
                inputs=safe_inputs,
            )

        try:
            verified = _hasher.verify(
                password,
                user["password_hash"],
            )
        except Exception:
            logger.exception("Stored credential hash could not be verified.")
            return fail(
                name=name,
                subcategory=sub,
                description=desc,
                code="CREDENTIAL_VERIFICATION_FAILED",
                message="Unable to authenticate right now.",
                status=500,
                inputs=safe_inputs,
            )

        if not verified:
            return fail(
                name=name,
                subcategory=sub,
                description=desc,
                code="INVALID_CREDENTIALS",
                message="Email or password is incorrect.",
                status=401,
                inputs=safe_inputs,
            )

        access_token = make_access_token(user["id"])
        refresh_token = secrets.token_urlsafe(48)

        refresh_hash = hashlib.sha256(
            refresh_token.encode("utf-8")
        ).hexdigest()

        expires_at = (
            datetime.now(timezone.utc)
            + timedelta(days=_REFRESH_TTL_DAYS)
        )

        with get_connection() as connection:
            session = create_session(
                user_id=user["id"],
                refresh_token_hash=refresh_hash,
                expires_at=expires_at,
                connection=connection,
            )

        return success(
            name=name,
            subcategory=sub,
            description="Login successful.",
            outputs={
                "user": to_public_user(user),
                "access_token": access_token,
                "token_type": "Bearer",
                "expires_in": access_token_ttl(),
                "refresh_token": refresh_token,
                "refresh_expires_at": session["expires_at"].isoformat(),
                "session_id": str(session["id"]),
            },
            inputs=safe_inputs,
        )

    except Exception:
        logger.exception("Login failed.")

        return fail(
            name=name,
            subcategory=sub,
            description=desc,
            code="LOGIN_FAILED",
            message="Unable to log in right now.",
            status=500,
            inputs=safe_inputs,
        )