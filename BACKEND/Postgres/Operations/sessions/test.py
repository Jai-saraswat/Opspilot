"""PostgreSQL integration tests for OpsPilot session Operations.

Run from the project root:
    python -m BACKEND.Postgres.Operations.sessions.test

These tests use real PostgreSQL records. Use a development/test database,
not production. The expired-session cleanup tests call a global cleanup
operation, which may delete other expired session rows in that database.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

from psycopg.rows import dict_row

from BACKEND.Postgres.gateway import get_connection
from BACKEND.Postgres.Operations.sessions import errors as session_errors
from BACKEND.Postgres.Operations.sessions.create_session import (
    create_session,
)
from BACKEND.Postgres.Operations.sessions.get_session_by_id import (
    get_session_by_id,
)
from BACKEND.Postgres.Operations.sessions.get_session_by_token_hash import (
    get_session_by_token_hash,
)
from BACKEND.Postgres.Operations.sessions.list_user_sessions import (
    list_user_sessions,
)
from BACKEND.Postgres.Operations.sessions.revoke_session import (
    revoke_session,
)
from BACKEND.Postgres.Operations.sessions.revoke_user_sessions import (
    revoke_user_sessions,
)
from BACKEND.Postgres.Operations.sessions.delete_expired_sessions import (
    delete_expired_sessions,
)


class RollbackProbe(Exception):
    """Force a caller-owned transaction to roll back."""


class SessionsOperationsIntegrationTests(unittest.TestCase):
    """Verify session Operations against the configured PostgreSQL database."""

    @classmethod
    def setUpClass(cls) -> None:
        """Verify database connectivity and required tables."""
        with get_connection() as connection:
            with connection.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    "SELECT current_database() AS database_name"
                )
                row = cursor.fetchone()

                if row is None:
                    raise RuntimeError(
                        "Unable to determine the PostgreSQL database."
                    )

                cls.database_name = row["database_name"]

                if any(
                    marker in cls.database_name.lower()
                    for marker in ("prod", "production", "live")
                ):
                    raise RuntimeError(
                        "Refusing to run tests against a "
                        f"production-looking database: {cls.database_name!r}"
                    )

                for table_name in ("users", "login_sessions"):
                    cursor.execute(
                        "SELECT to_regclass(%s) AS table_name",
                        (f"public.{table_name}",),
                    )
                    result = cursor.fetchone()

                    if result is None or result["table_name"] is None:
                        raise RuntimeError(
                            f"Required table public.{table_name} was not "
                            "found. Initialize the schema first."
                        )

        print(
            f"\nConnected to PostgreSQL database: {cls.database_name}"
        )

    def setUp(self) -> None:
        """Create isolated test users."""
        self.marker = uuid4().hex
        self.created_user_ids: list[UUID] = []

        self.user_a = self._create_test_user("alpha")
        self.user_b = self._create_test_user("beta")

    def tearDown(self) -> None:
        """Remove sessions and users owned by the current test."""
        with get_connection() as connection:
            with connection.cursor() as cursor:
                for user_id in self.created_user_ids:
                    cursor.execute(
                        """
                        DELETE FROM login_sessions
                        WHERE user_id = %s;
                        """,
                        (user_id,),
                    )

                for user_id in self.created_user_ids:
                    cursor.execute(
                        "DELETE FROM users WHERE id = %s;",
                        (user_id,),
                    )

    # =========================================================
    # FIXTURE HELPERS
    # =========================================================

    def _create_test_user(self, suffix: str) -> UUID:
        """Insert a disposable user required by the session foreign key."""
        email = f"session-test-{self.marker}-{suffix}@example.invalid"

        with get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO users (
                        full_name,
                        email,
                        password_hash
                    )
                    VALUES (%s, %s, %s)
                    RETURNING id;
                    """,
                    (
                        f"Session Test {suffix} {self.marker}",
                        email,
                        f"test-only-hash-{uuid4().hex}",
                    ),
                )
                user_id = UUID(str(cursor.fetchone()[0]))

        self.created_user_ids.append(user_id)
        return user_id

    @staticmethod
    def _new_token_hash() -> str:
        """Generate a unique test hash; this is not a real refresh token."""
        return f"test-refresh-hash-{uuid4().hex}"

    def _create_valid_session(
        self,
        user_id: UUID | None = None,
        *,
        days_valid: int = 7,
    ) -> dict[str, Any]:
        """Create a session through the operation and read it from PostgreSQL."""
        user_id = user_id or self.user_a
        token_hash = self._new_token_hash()
        expires_at = datetime.now(timezone.utc) + timedelta(
            days=days_valid
        )

        # create_session() is keyword-only and deliberately does not return
        # refresh_token_hash. Read the full test record directly afterward.
        create_session(
            user_id=user_id,
            refresh_token_hash=token_hash,
            expires_at=expires_at,
        )

        stored = self._fetch_session_by_hash(token_hash)

        if stored is None:
            raise AssertionError(
                "create_session returned without persisting the session."
            )

        return stored

    def _insert_expired_session(self, user_id: UUID) -> UUID:
        """Insert a long-expired session to test database cleanup."""
        token_hash = self._new_token_hash()

        with get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO login_sessions (
                        user_id,
                        refresh_token_hash,
                        created_at,
                        expires_at
                    )
                    VALUES (
                        %s,
                        %s,
                        TIMESTAMPTZ '2000-01-01 00:00:00+00',
                        TIMESTAMPTZ '2000-01-02 00:00:00+00'
                    )
                    RETURNING id;
                    """,
                    (user_id, token_hash),
                )
                return UUID(str(cursor.fetchone()[0]))

    def _fetch_session_by_id(
        self,
        session_id: UUID,
    ) -> dict[str, Any] | None:
        """Read the authoritative session row by ID."""
        with get_connection() as connection:
            with connection.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    """
                    SELECT
                        id,
                        user_id,
                        refresh_token_hash,
                        expires_at,
                        revoked_at,
                        created_at
                    FROM login_sessions
                    WHERE id = %s;
                    """,
                    (session_id,),
                )
                row = cursor.fetchone()

        return dict(row) if row is not None else None

    def _fetch_session_by_hash(
        self,
        token_hash: str,
    ) -> dict[str, Any] | None:
        """Read the authoritative session row by its hash."""
        with get_connection() as connection:
            with connection.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    """
                    SELECT
                        id,
                        user_id,
                        refresh_token_hash,
                        expires_at,
                        revoked_at,
                        created_at
                    FROM login_sessions
                    WHERE refresh_token_hash = %s;
                    """,
                    (token_hash,),
                )
                row = cursor.fetchone()

        return dict(row) if row is not None else None

    @staticmethod
    def _extract_rows(result: Any) -> list[dict[str, Any]]:
        """Normalize common paginated/list operation result shapes."""
        if isinstance(result, list):
            if not all(isinstance(row, dict) for row in result):
                raise AssertionError(
                    "List operation returned entries that are not dictionaries."
                )
            return result

        if isinstance(result, tuple) and result:
            if isinstance(result[0], list):
                return (
                    SessionsOperationsIntegrationTests
                    ._extract_rows(result[0])
                )

        if isinstance(result, dict):
            if "id" in result and "user_id" in result:
                return [result]

            for key in (
                "sessions",
                "items",
                "records",
                "results",
                "data",
            ):
                value = result.get(key)

                if isinstance(value, list):
                    if not all(isinstance(row, dict) for row in value):
                        raise AssertionError(
                            f"The {key!r} result contains invalid records."
                        )
                    return value

                if isinstance(value, dict):
                    return (
                        SessionsOperationsIntegrationTests
                        ._extract_rows(value)
                    )

        raise AssertionError(
            "Unexpected list operation result type: "
            f"{type(result).__name__}"
        )

    # =========================================================
    # errors.py
    # =========================================================

    def test_session_errors_module_exposes_domain_exceptions(
        self,
    ) -> None:
        """Check the expected session-specific error classes."""
        for name in (
            "InvalidSessionRecordError",
            "SessionUserNotFoundError",
            "SessionDatabaseError",
        ):
            with self.subTest(exception=name):
                exception_type = getattr(session_errors, name)
                self.assertTrue(issubclass(exception_type, Exception))

    # =========================================================
    # create_session.py
    # =========================================================

    def test_create_session_persists_valid_session(self) -> None:
        token_hash = self._new_token_hash()
        expires_at = datetime.now(timezone.utc) + timedelta(days=7)

        result = create_session(
            user_id=self.user_a,
            refresh_token_hash=token_hash,
            expires_at=expires_at,
        )

        self.assertIsInstance(result, dict)
        self.assertNotIn(
            "refresh_token_hash",
            result,
            "create_session should return only non-sensitive session fields.",
        )

        stored = self._fetch_session_by_hash(token_hash)

        self.assertIsNotNone(stored)
        assert stored is not None

        self.assertEqual(stored["user_id"], self.user_a)
        self.assertEqual(stored["refresh_token_hash"], token_hash)
        self.assertIsNotNone(stored["id"])
        self.assertIsNotNone(stored["created_at"])
        self.assertIsNone(stored["revoked_at"])

    def test_create_session_rejects_nonexistent_user(self) -> None:
        with self.assertRaises(
            session_errors.SessionUserNotFoundError
        ):
            create_session(
                user_id=uuid4(),
                refresh_token_hash=self._new_token_hash(),
                expires_at=datetime.now(timezone.utc) + timedelta(days=1),
            )

    def test_create_session_rejects_expired_expiry_time(self) -> None:
        with self.assertRaises(
            session_errors.InvalidSessionRecordError
        ):
            create_session(
                user_id=self.user_a,
                refresh_token_hash=self._new_token_hash(),
                expires_at=datetime.now(timezone.utc) - timedelta(minutes=5),
            )

    # =========================================================
    # get_session_by_id.py
    # =========================================================

    def test_get_session_by_id_returns_existing_session(self) -> None:
        created = self._create_valid_session()

        result = get_session_by_id(created["id"])

        self.assertIsNotNone(result)
        self.assertEqual(result["id"], created["id"])
        self.assertEqual(result["user_id"], self.user_a)

    def test_get_session_by_id_returns_none_when_missing(self) -> None:
        self.assertIsNone(get_session_by_id(uuid4()))

    # =========================================================
    # get_session_by_token_hash.py
    # =========================================================

    def test_get_session_by_token_hash_returns_matching_session(
        self,
    ) -> None:
        created = self._create_valid_session()

        result = get_session_by_token_hash(
            created["refresh_token_hash"]
        )

        self.assertIsNotNone(result)
        self.assertEqual(result["id"], created["id"])
        self.assertEqual(result["user_id"], self.user_a)

    def test_get_session_by_token_hash_returns_none_when_missing(
        self,
    ) -> None:
        result = get_session_by_token_hash(self._new_token_hash())
        self.assertIsNone(result)

    # =========================================================
    # list_user_sessions.py
    # =========================================================

    def test_list_user_sessions_returns_only_requested_users_sessions(
        self,
    ) -> None:
        session_a = self._create_valid_session(self.user_a)
        session_b = self._create_valid_session(self.user_a)
        other_user_session = self._create_valid_session(self.user_b)

        rows = self._extract_rows(
            list_user_sessions(
                self.user_a,
                limit=50,
                offset=0,
            )
        )

        returned_ids = {str(row["id"]) for row in rows}

        self.assertIn(str(session_a["id"]), returned_ids)
        self.assertIn(str(session_b["id"]), returned_ids)
        self.assertNotIn(str(other_user_session["id"]), returned_ids)

        self.assertTrue(
            all(
                str(row["user_id"]) == str(self.user_a)
                for row in rows
            ),
            "list_user_sessions returned a session for another user.",
        )

    def test_list_user_sessions_supports_pagination(self) -> None:
        created_sessions = [
            self._create_valid_session(self.user_a)
            for _ in range(3)
        ]

        page_one = self._extract_rows(
            list_user_sessions(
                self.user_a,
                limit=1,
                offset=0,
            )
        )
        page_two = self._extract_rows(
            list_user_sessions(
                self.user_a,
                limit=1,
                offset=1,
            )
        )

        self.assertEqual(len(page_one), 1)
        self.assertEqual(len(page_two), 1)

        first_id = str(page_one[0]["id"])
        second_id = str(page_two[0]["id"])

        self.assertNotEqual(
            first_id,
            second_id,
            "Adjacent pages returned the same session.",
        )

        fixture_ids = {
            str(session["id"])
            for session in created_sessions
        }

        self.assertIn(first_id, fixture_ids)
        self.assertIn(second_id, fixture_ids)

    def test_list_user_sessions_returns_empty_for_user_without_sessions(
        self,
    ) -> None:
        result = list_user_sessions(
            self.user_a,
            limit=50,
            offset=0,
        )

        self.assertEqual(self._extract_rows(result), [])

    # =========================================================
    # revoke_session.py
    # =========================================================

    def test_revoke_session_sets_revoked_at(self) -> None:
        created = self._create_valid_session()

        revoke_session(created["id"])

        stored = self._fetch_session_by_id(created["id"])

        self.assertIsNotNone(stored)
        assert stored is not None

        self.assertIsNotNone(stored["revoked_at"])
        self.assertGreaterEqual(
            stored["revoked_at"],
            stored["created_at"],
        )

    def test_revoke_session_is_idempotent(self) -> None:
        created = self._create_valid_session()

        revoke_session(created["id"])

        first_read = self._fetch_session_by_id(created["id"])
        self.assertIsNotNone(first_read)
        assert first_read is not None

        first_revoked_at = first_read["revoked_at"]
        self.assertIsNotNone(first_revoked_at)

        revoke_session(created["id"])

        second_read = self._fetch_session_by_id(created["id"])
        self.assertIsNotNone(second_read)
        assert second_read is not None

        self.assertEqual(
            second_read["revoked_at"],
            first_revoked_at,
            "Repeated revocation changed the original timestamp.",
        )

    def test_revoke_session_does_not_create_missing_session(self) -> None:
        missing_id = uuid4()

        revoke_session(missing_id)

        self.assertIsNone(self._fetch_session_by_id(missing_id))

    # =========================================================
    # revoke_user_sessions.py
    # =========================================================

    def test_revoke_user_sessions_revokes_all_users_sessions(
        self,
    ) -> None:
        session_a = self._create_valid_session(self.user_a)
        session_b = self._create_valid_session(self.user_a)

        revoke_user_sessions(self.user_a)

        stored_a = self._fetch_session_by_id(session_a["id"])
        stored_b = self._fetch_session_by_id(session_b["id"])

        self.assertIsNotNone(stored_a)
        self.assertIsNotNone(stored_b)
        assert stored_a is not None
        assert stored_b is not None

        self.assertIsNotNone(stored_a["revoked_at"])
        self.assertIsNotNone(stored_b["revoked_at"])

    def test_revoke_user_sessions_does_not_affect_other_users(
        self,
    ) -> None:
        target_session = self._create_valid_session(self.user_a)
        other_session = self._create_valid_session(self.user_b)

        revoke_user_sessions(self.user_a)

        stored_target = self._fetch_session_by_id(target_session["id"])
        stored_other = self._fetch_session_by_id(other_session["id"])

        self.assertIsNotNone(stored_target)
        self.assertIsNotNone(stored_other)
        assert stored_target is not None
        assert stored_other is not None

        self.assertIsNotNone(stored_target["revoked_at"])
        self.assertIsNone(
            stored_other["revoked_at"],
            "Revoking one user's sessions affected another user.",
        )

    # =========================================================
    # delete_expired_sessions.py
    # =========================================================

    def test_delete_expired_sessions_removes_expired_rows_only(
        self,
    ) -> None:
        expired_id = self._insert_expired_session(self.user_a)
        active_session = self._create_valid_session(
            self.user_a,
            days_valid=7,
        )

        self.assertIsNotNone(self._fetch_session_by_id(expired_id))
        self.assertIsNotNone(
            self._fetch_session_by_id(active_session["id"])
        )

        delete_expired_sessions()

        self.assertIsNone(
            self._fetch_session_by_id(expired_id),
            "The expired session was not deleted.",
        )
        self.assertIsNotNone(
            self._fetch_session_by_id(active_session["id"]),
            "Cleanup deleted a non-expired session.",
        )

    def test_delete_expired_sessions_preserves_active_other_user_session(
        self,
    ) -> None:
        other_user_session = self._create_valid_session(
            self.user_b,
            days_valid=7,
        )

        delete_expired_sessions()

        stored = self._fetch_session_by_id(other_user_session["id"])

        self.assertIsNotNone(stored)
        assert stored is not None
        self.assertIsNone(stored["revoked_at"])

    # =========================================================
    # CALLER-OWNED TRANSACTION
    # =========================================================

    def test_create_session_respects_caller_owned_transaction(
        self,
    ) -> None:
        token_hash = self._new_token_hash()
        expires_at = datetime.now(timezone.utc) + timedelta(days=1)

        with self.assertRaises(RollbackProbe):
            with get_connection() as connection:
                create_session(
                    user_id=self.user_a,
                    refresh_token_hash=token_hash,
                    expires_at=expires_at,
                    connection=connection,
                )

                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT COUNT(*)
                        FROM login_sessions
                        WHERE refresh_token_hash = %s;
                        """,
                        (token_hash,),
                    )
                    self.assertEqual(cursor.fetchone()[0], 1)

                raise RollbackProbe(
                    "Force caller-owned transaction rollback."
                )

        self.assertIsNone(
            self._fetch_session_by_hash(token_hash),
            "create_session committed a transaction owned by its caller.",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)