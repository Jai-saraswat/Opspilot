"""Change the authenticated user's password."""

from __future__ import annotations

import logging
from typing import Any

from pwdlib import PasswordHash

from BACKEND.Postgres.Operations.users.get_user_by_id import (
    get_user_by_id,
)
from BACKEND.Postgres.Operations.users.get_user_auth_record_by_email import (
    get_user_auth_record_by_email,
)
from BACKEND.Postgres.Operations.users.update_user_password_hash import (
    update_user_password_hash,
)
from BACKEND.Postgres.Operations.sessions.revoke_user_sessions import (
    revoke_user_sessions,
)
from BACKEND.Services.account._common import (
    fail,
    success,
    parse_uuid,
)
from BACKEND.Services.idempotency import execute_idempotently

logger = logging.getLogger(__name__)
_hasher = PasswordHash.recommended()


def change_password(
    *,
    user_id: str,
    current_password: str,
    new_password: str,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    name = "change_password"
    sub = "password"
    desc = "Change the authenticated user's password."
    inputs = {"user_id": str(user_id)}

    try:
        actor_id = parse_uuid(user_id)
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

    if not isinstance(current_password, str) or not current_password:
        return fail(
            name=name,
            subcategory=sub,
            description=desc,
            code="CURRENT_PASSWORD_REQUIRED",
            message="Current password is required.",
            status=400,
            inputs=inputs,
        )

    if (
        not isinstance(new_password, str)
        or not 12 <= len(new_password) <= 128
    ):
        return fail(
            name=name,
            subcategory=sub,
            description=desc,
            code="INVALID_NEW_PASSWORD",
            message="New password must contain 12–128 characters.",
            status=400,
            inputs=inputs,
        )

    if current_password == new_password:
        return fail(
            name=name,
            subcategory=sub,
            description=desc,
            code="PASSWORD_UNCHANGED",
            message="The new password must differ from the current password.",
            status=400,
            inputs=inputs,
        )

    try:
        def _change(connection):
            user = get_user_by_id(
                actor_id,
                connection=connection,
            )

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

            if user["account_status"] != "active":
                return fail(
                    name=name,
                    subcategory=sub,
                    description=desc,
                    code="ACCOUNT_INACTIVE",
                    message="This account cannot change its password.",
                    status=403,
                    inputs=inputs,
                )

            auth = get_user_auth_record_by_email(
                user["email"],
                connection=connection,
            )

            if (
                not auth
                or not _hasher.verify(
                    current_password,
                    auth["password_hash"],
                )
            ):
                return fail(
                    name=name,
                    subcategory=sub,
                    description=desc,
                    code="INCORRECT_CURRENT_PASSWORD",
                    message="Current password is incorrect.",
                    status=401,
                    inputs=inputs,
                )

            updated = update_user_password_hash(
                actor_id,
                _hasher.hash(new_password),
                connection=connection,
            )

            if not updated:
                return fail(
                    name=name,
                    subcategory=sub,
                    description=desc,
                    code="ACCOUNT_NOT_FOUND",
                    message="Account not found.",
                    status=404,
                    inputs=inputs,
                )

            revoked_count = revoke_user_sessions(
                actor_id,
                connection=connection,
            )

            return success(
                name=name,
                subcategory=sub,
                description=(
                    "Password changed; existing refresh sessions were revoked."
                ),
                outputs={
                    "password_changed": True,
                    "sessions_revoked": revoked_count,
                },
                inputs=inputs,
            )

        return execute_idempotently(
            user_id=actor_id,
            idempotency_key=idempotency_key,
            operation_name=name,
            category="account",
            subcategory=sub,
            description=desc,
            payload={
                "current_password": current_password,
                "new_password": new_password,
            },
            operation=_change,
        )

    except Exception:
        logger.exception("Password change failed.")

        return fail(
            name=name,
            subcategory=sub,
            description=desc,
            code="PASSWORD_CHANGE_FAILED",
            message="Unable to change the password right now.",
            status=500,
            inputs=inputs,
        )