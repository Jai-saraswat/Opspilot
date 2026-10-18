"""Register a user and assign the default standard_user role atomically."""

from __future__ import annotations

import logging
import re
from typing import Any

from pwdlib import PasswordHash

from BACKEND.Postgres.gateway import get_connection
from BACKEND.Postgres.Operations.users.create_user import (
    create_user as create_user_op,
)
from BACKEND.Postgres.Operations.users.errors import (
    UserAlreadyExistsError,
    InvalidUserRecordError,
    UserCreationError,
)
from BACKEND.Postgres.Operations.authorization.get_role_by_name import (
    get_role_by_name,
)
from BACKEND.Postgres.Operations.authorization.assign_role_to_user import (
    assign_role_to_user,
)
from BACKEND.Services.account._common import (
    fail,
    success,
    to_public_user,
)

logger = logging.getLogger(__name__)
_hasher = PasswordHash.recommended()
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def register_user(
    *,
    full_name: str,
    email: str,
    password: str,
) -> dict[str, Any]:
    name = "register_user"
    sub = "registration"
    desc = "Register a new OpsPilot account."

    safe_inputs = {
        "full_name": full_name if isinstance(full_name, str) else "",
        "email": email if isinstance(email, str) else "",
    }

    if not all(
        isinstance(value, str)
        for value in (full_name, email, password)
    ):
        return fail(
            name=name,
            subcategory=sub,
            description=desc,
            code="INVALID_INPUT",
            message="Name, email, and password must be strings.",
            status=400,
            inputs=safe_inputs,
        )

    full_name = full_name.strip()
    email = email.strip().casefold()

    safe_inputs = {"full_name": full_name, "email": email}

    if not full_name or len(full_name) > 150:
        return fail(
            name=name,
            subcategory=sub,
            description=desc,
            code="INVALID_NAME",
            message="Name must contain 1–150 characters.",
            status=400,
            inputs=safe_inputs,
        )

    if len(email) > 254 or not _EMAIL.fullmatch(email):
        return fail(
            name=name,
            subcategory=sub,
            description=desc,
            code="INVALID_EMAIL",
            message="Provide a valid email address.",
            status=400,
            inputs=safe_inputs,
        )

    if not 12 <= len(password) <= 128:
        return fail(
            name=name,
            subcategory=sub,
            description=desc,
            code="INVALID_PASSWORD",
            message="Password must contain 12–128 characters.",
            status=400,
            inputs=safe_inputs,
        )

    try:
        password_hash = _hasher.hash(password)

        # User creation and default-role assignment share one transaction.
        with get_connection() as connection:
            user = create_user_op(
                full_name=full_name,
                email=email,
                password_hash=password_hash,
                connection=connection,
            )

            role = get_role_by_name(
                "standard_user",
                "system",
                connection=connection,
            )

            if role is None:
                raise RuntimeError(
                    "Required system role 'standard_user' is not seeded."
                )

            assign_role_to_user(
                user_id=user["id"],
                role_id=role["id"],
                assigned_by=None,
                connection=connection,
            )

        return success(
            name=name,
            subcategory=sub,
            description="Account registered successfully.",
            outputs={"user": to_public_user(user)},
            inputs=safe_inputs,
            status=201,
        )

    except UserAlreadyExistsError:
        return fail(
            name=name,
            subcategory=sub,
            description=desc,
            code="EMAIL_ALREADY_REGISTERED",
            message="An account with this email already exists.",
            status=409,
            inputs=safe_inputs,
        )

    except InvalidUserRecordError:
        return fail(
            name=name,
            subcategory=sub,
            description=desc,
            code="INVALID_USER_RECORD",
            message="The supplied account details are invalid.",
            status=400,
            inputs=safe_inputs,
        )

    except UserCreationError:
        logger.exception("User creation failed during registration.")

        return fail(
            name=name,
            subcategory=sub,
            description=desc,
            code="USER_CREATION_FAILED",
            message="Unable to create the account right now.",
            status=500,
            inputs=safe_inputs,
        )

    except Exception:
        logger.exception("Registration failed.")

        return fail(
            name=name,
            subcategory=sub,
            description=desc,
            code="REGISTRATION_FAILED",
            message=(
                "Unable to register the account right now. "
                "Check server configuration and seeded roles."
            ),
            status=500,
            inputs=safe_inputs,
        )