
"""Drop every table in the public schema."""

from psycopg import sql

from gateway import get_connection


def drop_tables() -> bool:
    if input(
        "This permanently drops every public table and its data. Type DROP to continue: "
    ) != "DROP":
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

                for table in tables:
                    cursor.execute(
                        sql.SQL("DROP TABLE {} CASCADE").format(
                            sql.Identifier("public", table)
                        )
                    )
                    print(f"Dropped: {table}")

        print(f"Dropped {len(tables)} table(s).")
        return True

    except Exception as exc:
        print(f"Drop operation failed: {exc}")
        return False


if __name__ == "__main__":
    raise SystemExit(0 if drop_tables() else 1)
