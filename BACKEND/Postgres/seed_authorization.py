"""Seed OpsPilot's built-in roles and permissions.

Run from the project root:

    python -m BACKEND.Postgres.seed_authorization

Bootstrap an existing user as the first system administrator:

    python -m BACKEND.Postgres.seed_authorization \
        --bootstrap-admin-email admin@example.com
"""

from __future__ import annotations

import argparse

from BACKEND.Postgres.gateway import get_connection


# ============================================================
# PERMISSION CATALOGUE
# ============================================================

PERMISSIONS = {
    # Accounts
    "accounts:list":
        "List, search, and filter accounts.",
    "accounts:read:any":
        "Read another user's account details.",
    "accounts:update:any":
        "Update another user's account profile.",
    "accounts:status:update":
        "Suspend, reactivate, or deactivate accounts.",

    # Teams
    "teams:create":
        "Create teams.",
    "teams:read:any":
        "Read team details beyond the user's own memberships.",
    "teams:update:any":
        "Update team details.",
    "teams:delete:any":
        "Delete eligible teams.",
    "teams:members:manage":
        "Add, remove, and manage team memberships.",

    # Cross-team permissions required by Services.
    # These broad permissions are granted to system_admin by default.
    "teams:list:any":
        "List teams beyond the user's own memberships.",
    "teams:manage:any":
        "Manage teams across team boundaries.",
    "teams:members:manage:any":
        "Manage memberships across team boundaries.",
    "teams:members:read:any":
        "Read membership records across team boundaries.",
    "teams:members:role:update:any":
        "Change membership roles across team boundaries.",

    # Authorization administration
    "roles:manage":
        "Manage role assignments and role permissions.",

    # Work items
    "work_items:create":
        "Create operational work items.",
    "work_items:read":
        "Read work items the user is authorized to access.",
    "work_items:update":
        "Update eligible work items.",
    "work_items:claim":
        "Claim an unassigned work item.",
    "work_items:assign":
        "Assign work items to eligible users.",
    "work_items:status:update":
        "Change work-item status.",
    "work_items:priority:update":
        "Change work-item priority.",

    # Cross-team permissions required by Services.
    # Keep these out of standard_user and approver defaults.
    "work_items:create:any":
        "Create work items outside the actor's own team memberships.",
    "work_items:read:any":
        "Read work items across team boundaries.",
    "work_items:list:any":
        "List work items across team boundaries.",
    "work_items:manage:any":
        "Manage work items across team boundaries.",
    "work_items:update:any":
        "Update work items across team boundaries.",
    "work_items:assign:any":
        "Assign work items across team boundaries.",
    "work_items:status:any":
        "Change work-item status across team boundaries.",
    "work_items:priority:any":
        "Change work-item priority across team boundaries.",

    # Approvals
    "approvals:create":
        "Request approval for an eligible work item.",
    "approvals:read":
        "Read approval requests the user may access.",
    "approvals:assign":
        "Assign an eligible approval approver.",
    "approvals:decide":
        "Approve or reject an eligible request.",

    # Cross-team permissions required by Services.
    "approvals:assign:any":
        "Assign approval approvers across team boundaries.",
    "approvals:read:any":
        "Read approval requests beyond the actor's own requests and teams.",

    # Activity and overview
    "activity:read":
        "Read activity history for accessible work items.",
    "dashboard:read":
        "View the operational dashboard.",
}


# ============================================================
# BUILT-IN SYSTEM ROLES
# ============================================================

ROLE_PERMISSIONS = {
    # The system administrator receives every catalogued permission,
    # including the cross-team permissions defined above.
    "system_admin": set(PERMISSIONS),

    # Ordinary users retain their existing scoped permissions.
    "standard_user": {
        "work_items:create",
        "work_items:read",
        "work_items:update",
        "work_items:claim",
        "work_items:status:update",
        "work_items:priority:update",
        "approvals:create",
        "approvals:read",
        "activity:read",
        "dashboard:read",
    },

    # Approvers retain their existing approval-focused permissions.
    "approver": {
        "approvals:read",
        "approvals:decide",
        "activity:read",
        "dashboard:read",
    },
}

ROLE_DESCRIPTIONS = {
    "system_admin": "Built-in system administrator role.",
    "standard_user": "Default role for ordinary application users.",
    "approver": "Grants approval decision capabilities.",
}


# ============================================================
# SEEDING
# ============================================================

def seed_authorization(
    bootstrap_admin_email: str | None = None,
) -> None:
    """Create or synchronize built-in authorization data."""

    with get_connection() as connection:
        with connection.cursor() as cursor:

            # ------------------------------------------------
            # 1. Seed permission records
            # ------------------------------------------------

            permission_ids = {}

            for key, description in PERMISSIONS.items():
                cursor.execute(
                    """
                    INSERT INTO permissions (
                        permission_key,
                        description
                    )
                    VALUES (%s, %s)
                    ON CONFLICT (permission_key)
                    DO UPDATE SET
                        description = EXCLUDED.description
                    RETURNING id
                    """,
                    (key, description),
                )

                permission_ids[key] = cursor.fetchone()[0]

            # ------------------------------------------------
            # 2. Seed built-in system roles
            # ------------------------------------------------

            role_ids = {}

            for name, description in ROLE_DESCRIPTIONS.items():
                cursor.execute(
                    """
                    INSERT INTO roles (
                        name,
                        scope,
                        description,
                        is_system_role
                    )
                    VALUES (%s, 'system', %s, TRUE)
                    ON CONFLICT (scope, name)
                    DO UPDATE SET
                        description = EXCLUDED.description,
                        is_system_role = TRUE
                    RETURNING id
                    """,
                    (name, description),
                )

                role_ids[name] = cursor.fetchone()[0]

            # ------------------------------------------------
            # 3. Synchronize role-permission mappings
            # ------------------------------------------------

            for role_name, permission_keys in ROLE_PERMISSIONS.items():
                role_id = role_ids[role_name]

                # This script defines the default permissions for
                # built-in roles. Re-running it replaces their grants.
                # Existing user-to-role assignments remain intact.
                cursor.execute(
                    """
                    DELETE FROM role_permissions
                    WHERE role_id = %s
                    """,
                    (role_id,),
                )

                mappings = [
                    (role_id, permission_ids[key])
                    for key in sorted(permission_keys)
                ]

                if mappings:
                    cursor.executemany(
                        """
                        INSERT INTO role_permissions (
                            role_id,
                            permission_id
                        )
                        VALUES (%s, %s)
                        ON CONFLICT DO NOTHING
                        """,
                        mappings,
                    )

            # ------------------------------------------------
            # 4. Optional explicit first-admin bootstrap
            # ------------------------------------------------

            if bootstrap_admin_email:
                cursor.execute(
                    """
                    SELECT id
                    FROM users
                    WHERE LOWER(email) = LOWER(%s)
                    """,
                    (bootstrap_admin_email.strip(),),
                )

                row = cursor.fetchone()

                if row is None:
                    raise ValueError(
                        "The bootstrap administrator account does not "
                        "exist. Register the account first, then rerun "
                        "the seed command with its email."
                    )

                admin_user_id = row[0]
                admin_role_id = role_ids["system_admin"]

                cursor.execute(
                    """
                    INSERT INTO user_roles (
                        user_id,
                        role_id,
                        assigned_by
                    )
                    VALUES (%s, %s, NULL)
                    ON CONFLICT (user_id, role_id) DO NOTHING
                    """,
                    (admin_user_id, admin_role_id),
                )

    # The connection context has successfully committed by this point.
    print("OpsPilot authorization seed completed.")
    print(f"Permissions processed: {len(PERMISSIONS)}")
    print(f"Built-in system roles processed: {len(ROLE_PERMISSIONS)}")

    if bootstrap_admin_email:
        print(
            "Bootstrap administrator role assigned "
            "to the specified account."
        )


# ============================================================
# COMMAND LINE
# ============================================================

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Seed OpsPilot authorization data."
    )

    parser.add_argument(
        "--bootstrap-admin-email",
        default=None,
        help=(
            "Explicitly assign system_admin to an existing account. "
            "Use only during controlled initial setup."
        ),
    )

    args = parser.parse_args()

    if args.bootstrap_admin_email is not None:
        email = args.bootstrap_admin_email.strip()

        if not email:
            parser.error("--bootstrap-admin-email cannot be empty.")

        seed_authorization(email)
    else:
        seed_authorization()


if __name__ == "__main__":
    main()