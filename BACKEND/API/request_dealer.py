"""Shared request authentication and actor verification.

Responsibilities:
- Validate Bearer access tokens.
- Verify token claims and signature.
- Confirm that the authenticated account still exists and is active.
- Provide the trusted actor ID to API route handlers.

Business authorization remains in the existing Services layer.
This module does not access PostgreSQL directly or implement role rules.
"""

from __future__ import annotations

import logging
import os
from uuid import UUID

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import (
    HTTPAuthorizationCredentials,
    HTTPBearer,
)

from BACKEND.Services.account.get_account_status import (
    get_account_status,
)


logger = logging.getLogger(__name__)

_bearer_scheme = HTTPBearer(auto_error=False)


def _authentication_error() -> HTTPException:
    """Return a consistent missing/invalid-token response."""

    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Valid access-token authentication is required.",
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_verified_actor_id(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(
        _bearer_scheme
    ),
) -> str:
    """Authenticate a request and return the trusted actor's UUID.

    Intended for use as a FastAPI dependency:

        actor_user_id: str = Depends(get_verified_actor_id)

    The client cannot choose the actor ID; it is derived from the
    verified access token.
    """

    # --------------------------------------------------------
    # 1. Require Bearer authentication
    # --------------------------------------------------------

    if (
        credentials is None
        or credentials.scheme.lower() != "bearer"
        or not credentials.credentials
    ):
        raise _authentication_error()

    # --------------------------------------------------------
    # 2. Load and validate server-side token configuration
    # --------------------------------------------------------

    secret = os.getenv("ACCESS_TOKEN_SECRET", "")

    if len(secret) < 32:
        logger.error(
            "ACCESS_TOKEN_SECRET is missing or incorrectly configured."
        )

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Authentication is not configured correctly.",
        )

    # --------------------------------------------------------
    # 3. Verify the signed access token
    # --------------------------------------------------------

    try:
        payload = jwt.decode(
            credentials.credentials,
            secret,
            algorithms=["HS256"],
            options={
                "require": [
                    "sub",
                    "iat",
                    "exp",
                    "jti",
                    "token_type",
                ],
            },
        )

        # Access tokens must not be confused with refresh tokens.
        if payload.get("token_type") != "access":
            raise _authentication_error()

        if not isinstance(payload.get("jti"), str):
            raise _authentication_error()

        # Canonicalize and validate the account identifier.
        actor_user_id = str(UUID(payload["sub"]))

    except HTTPException:
        raise

    except (jwt.InvalidTokenError, ValueError, TypeError, KeyError):
        raise _authentication_error() from None

    # --------------------------------------------------------
    # 4. Verify the account using the existing Service
    # --------------------------------------------------------

    # Never query PostgreSQL directly from the API layer.
    # This Service uses the existing account/Operations contracts.
    try:
        account_result = get_account_status(
            actor_user_id=actor_user_id,
        )
    except Exception:
        logger.exception("Unable to verify the authenticated account.")

        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Unable to verify account status.",
        ) from None

    if not account_result.success:
        service_status = account_result.http_status

        # A token whose subject no longer resolves to an account
        # must not authenticate successfully.
        if service_status in {400, 401, 403, 404}:
            raise _authentication_error()

        logger.warning(
            "Account verification failed with service status %s.",
            service_status,
        )

        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Unable to verify account status.",
        )

    account_data = account_result.outputs.data

    if not isinstance(account_data, dict):
        logger.error(
            "Account-status Service returned an invalid response."
        )

        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Unable to verify account status.",
        )

    if account_data.get("account_status") != "active":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account is not active.",
        )

    # --------------------------------------------------------
    # 5. Attach the verified identity to the request
    # --------------------------------------------------------

    request.state.actor_user_id = actor_user_id

    return actor_user_id