"""Change an account's active/suspended/deactivated state."""

from __future__ import annotations

import logging
from typing import Any

from BACKEND.Postgres.Operations.users.update_user_status import (
    update_user_status,
)
from BACKEND.Postgres.Operations.sessions.revoke_user_sessions import (
    revoke_user_sessions,
)
from BACKEND.Services.account._common import (
    fail,
    success,
    to_public_user,
    parse_uuid,
    actor_has_permission,
)
from BACKEND.Services.idempotency import execute_idempotently

logger = logging.getLogger(__name__)

_VALID = {"active", "suspended", "deactivated"}


def update_account_status(
    *,
    actor_user_id: str,
    target_user_id: str,
    account_status: str,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    name = "update_account_status"
    sub = "account_status"
    desc = "Change an account's status."

    inputs = {
        "target_user_id": str(target_user_id),
        "account_status": account_status,
    }

    try:
        actor_id = parse_uuid(actor_user_id)
        target_id = parse_uuid(target_user_id)

        if not actor_has_permission(
            actor_id,
            "accounts:status:update",
        ):
            return fail(
                name=name,
                subcategory=sub,
                description=desc,
                code="FORBIDDEN",
                message="You are not allowed to change account status.",
                status=403,
                inputs=inputs,
            )

        if account_status not in _VALID:
            return fail(
                name=name,
                subcategory=sub,
                description=desc,
                code="INVALID_STATUS",
                message="Status must be active, suspended, or deactivated.",
                status=400,
                inputs=inputs,
            )

        if actor_id == target_id and account_status != "active":
            return fail(
                name=name,
                subcategory=sub,
                description=desc,
                code="SELF_LOCKOUT_PREVENTED",
                message="You cannot suspend or deactivate your own account.",
                status=409,
                inputs=inputs,
            )

        def _update_status(connection):
            user = update_user_status(
                target_id,
                account_status,
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

            revoked = (
                revoke_user_sessions(
                    target_id,
                    connection=connection,
                )
                if account_status != "active"
                else 0
            )

            return success(
                name=name,
                subcategory=sub,
                description="Account status updated successfully.",
                outputs={
                    "user": to_public_user(user),
                    "sessions_revoked": revoked,
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
                "target_user_id": str(target_id),
                "account_status": account_status,
            },
            operation=_update_status,
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
        logger.exception("Account status update failed.")

        return fail(
            name=name,
            subcategory=sub,
            description=desc,
            code="ACCOUNT_STATUS_UPDATE_FAILED",
            message="Unable to update account status right now.",
            status=500,
            inputs=inputs,
        )