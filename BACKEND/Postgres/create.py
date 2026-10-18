"""Initialize the OpsPilot database schema."""

from pathlib import Path

import psycopg

from gateway import get_connection


SCHEMA_DIR = Path(__file__).resolve().parent / "Schema"

SCHEMA_FILES = [
    "create_users.sql",
    "create_teams_and_team_memberships.sql",
    "create_roles_and_permissions_tables.sql",
    "create_work_items.sql",
    "create_work_item_activity_history.sql",
    "create_work_item_approval_requests.sql",
    "create_idempotency_records.sql",
    "create_login_sessions.sql",
]

EXPECTED_TABLES = {
    "users",
    "teams",
    "team_memberships",
    "roles",
    "permissions",
    "role_permissions",
    "user_roles",
    "user_permission_overrides",
    "work_items",
    "work_item_activity",
    "work_item_approval_requests",
    "idempotency_records",
    "login_sessions",
}


def create_schema() -> bool:
    scripts = []

    for filename in SCHEMA_FILES:
        path = SCHEMA_DIR / filename

        if not path.is_file():
            print(f"Missing schema file: {path}")
            return False

        sql = path.read_text(encoding="utf-8").strip()

        if not sql:
            print(f"Schema file is empty: {filename}")
            return False

        scripts.append((filename, sql))

    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT tablename
                    FROM pg_catalog.pg_tables
                    WHERE schemaname = 'public'
                    """
                )
                existing_tables = {row[0] for row in cursor.fetchall()}

            application_tables = existing_tables & EXPECTED_TABLES

            if application_tables == EXPECTED_TABLES:
                print("All expected tables already exist. Nothing to do.")
                return True

            if application_tables:
                missing = sorted(EXPECTED_TABLES - application_tables)
                print("Database schema is partially initialized.")
                print("Missing tables:", ", ".join(missing))
                print("No changes made. Resolve the schema manually.")
                return False

            if existing_tables:
                print(
                    "The public schema contains unrelated tables. "
                    "No changes made."
                )
                return False

            for filename, sql in scripts:
                with conn.cursor() as cursor:
                    cursor.execute(sql)

                print(f"Created: {filename}")

        print("Database schema created successfully.")
        return True

    except (psycopg.Error, OSError, RuntimeError) as exc:
        print(f"Schema creation failed: {exc}")
        return False


if __name__ == "__main__":
    raise SystemExit(0 if create_schema() else 1)