"""Update the authenticated user's own profile."""

from __future__ import annotations

import logging
import re
from typing import Any

from BACKEND.Postgres.Operations.users.update_user_profile import (
    update_user_profile,
)
from BACKEND.Postgres.Operations.users.errors import (
    UserAlreadyExistsError,
    InvalidUserRecordError,
)
from BACKEND.Services.account._common import (
    fail,
    success,
    to_public_user,
    parse_uuid,
)
from BACKEND.Services.idempotency import execute_idempotently

logger = logging.getLogger(__name__)
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def update_profile(
    *,
    actor_user_id: str,
    full_name: str | None = None,
    email: str | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    name = "update_profile"
    sub = "profile"
    desc = "Update the authenticated user's profile."
    inputs = {"full_name": full_name, "email": email}

    try:
        user_id = parse_uuid(actor_user_id)

        if full_name is None and email is None:
            return fail(
                name=name,
                subcategory=sub,
                description=desc,
                code="NO_CHANGES",
                message="Provide a name or email to update.",
                status=400,
                inputs=inputs,
            )

        if full_name is not None and (
            not isinstance(full_name, str)
            or not full_name.strip()
            or len(full_name.strip()) > 150
        ):
            return fail(
                name=name,
                subcategory=sub,
                description=desc,
                code="INVALID_NAME",
                message="Name must contain 1–150 characters.",
                status=400,
                inputs=inputs,
            )

        if email is not None and (
            not isinstance(email, str)
            or len(email.strip()) > 254
            or not _EMAIL.fullmatch(email.strip())
        ):
            return fail(
                name=name,
                subcategory=sub,
                description=desc,
                code="INVALID_EMAIL",
                message="Provide a valid email address.",
                status=400,
                inputs=inputs,
            )

        normalized_name = (
            full_name.strip() if full_name is not None else None
        )
        normalized_email = (
            email.strip().casefold() if email is not None else None
        )

        def _update(connection):
            updated = update_user_profile(
                user_id,
                full_name=normalized_name,
                email=normalized_email,
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

            return success(
                name=name,
                subcategory=sub,
                description="Profile updated successfully.",
                outputs={"user": to_public_user(updated)},
                inputs=inputs,
            )

        return execute_idempotently(
            user_id=user_id,
            idempotency_key=idempotency_key,
            operation_name=name,
            category="account",
            subcategory=sub,
            description=desc,
            payload={
                "full_name": normalized_name,
                "email": normalized_email,
            },
            operation=_update,
        )

    except UserAlreadyExistsError:
        return fail(
            name=name,
            subcategory=sub,
            description=desc,
            code="EMAIL_ALREADY_REGISTERED",
            message="An account with this email already exists.",
            status=409,
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

    except InvalidUserRecordError:
        return fail(
            name=name,
            subcategory=sub,
            description=desc,
            code="INVALID_PROFILE",
            message="One or more profile fields are invalid.",
            status=400,
            inputs=inputs,
        )

    except Exception:
        logger.exception("Profile update failed.")

        return fail(
            name=name,
            subcategory=sub,
            description=desc,
            code="PROFILE_UPDATE_FAILED",
            message="Unable to update your profile right now.",
            status=500,
            inputs=inputs,
        )