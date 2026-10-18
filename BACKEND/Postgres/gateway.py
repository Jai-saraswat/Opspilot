
"""PostgreSQL connection check for OpsPilot."""

import os
from pathlib import Path

import psycopg
from dotenv import load_dotenv
from psycopg.conninfo import make_conninfo


# Project root: Newtonite/
PROJECT_ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = PROJECT_ROOT / "DEPLOYEMENT" / ".env"

load_dotenv(ENV_FILE, override=False)


def get_connection():
    """Open a PostgreSQL connection using the configured database."""

    # Prefer a full connection URL, such as Render's DATABASE_URL.
    database_url = os.getenv("DATABASE_URL", "").strip()

    if database_url:
        return psycopg.connect(
            database_url,
            connect_timeout=5,
            application_name="opspilot",
        )

    # Preserve the existing local PostgreSQL configuration.
    required = (
        "POSTGRES_DB",
        "POSTGRES_USER",
        "POSTGRES_PASSWORD",
    )
    missing = [key for key in required if not os.getenv(key)]

    if missing:
        raise RuntimeError(
            f"Missing PostgreSQL configuration in {ENV_FILE}: "
            + ", ".join(missing)
        )

    conninfo = make_conninfo(
        host=os.getenv("POSTGRES_HOST", "127.0.0.1"),
        port=int(os.getenv("POSTGRES_PORT", "5432")),
        dbname=os.environ["POSTGRES_DB"],
        user=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"],
        connect_timeout=5,
        application_name="opspilot",
    )

    return psycopg.connect(conninfo)


def check_connection() -> bool:
    """Test the connection and print a concise status."""

    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()

        print("PostgreSQL connection successful.")
        return True

    except Exception as exc:
        print(f"PostgreSQL connection failed: {exc}")
        return False


if __name__ == "__main__":
    check_connection()
