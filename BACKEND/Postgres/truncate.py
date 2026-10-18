
"""Truncate every table in the public schema."""

from psycopg import sql

from gateway import get_connection


def truncate_database() -> bool:
    if input(
        "This deletes all data from every public table. Type TRUNCATE to continue: "
    ) != "TRUNCATE":
        print("Cancelled.")
        return False

    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT tablename
                    FROM pg_catalog.pg_tables
                    WHERE schemaname = 'public'
                    ORDER BY tablename
                """)
                tables = {row[0] for row in cursor.fetchall()}

                if not tables:
                    print("No tables found in the public schema.")
                    return True

                table_identifiers = [
                    sql.Identifier("public", table) for table in tables
                ]

                cursor.execute(
                    sql.SQL("TRUNCATE TABLE {} RESTART IDENTITY CASCADE").format(
                        sql.SQL(", ").join(table_identifiers)
                    )
                )

        print(f"Truncated {len(tables)} table(s). Structure preserved.")
        return True

    except Exception as exc:
        print(f"Truncation failed: {exc}")
        return False


if __name__ == "__main__":
    raise SystemExit(0 if truncate_database() else 1)
