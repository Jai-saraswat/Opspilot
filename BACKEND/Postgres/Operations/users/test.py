"""Database integration tests for the OpsPilot users Operations folder.

Run from the project root:
    python -m BACKEND.Postgres.Operations.users.test

These tests use a real PostgreSQL database configured through
BACKEND.Postgres.gateway.get_connection(). They create uniquely named
test users and delete only those users during cleanup.

Do not point this test suite at a production database.
"""

from __future__ import annotations

import unittest
from typing import Any
from uuid import UUID, uuid4

import psycopg
from psycopg.rows import dict_row

from BACKEND.Postgres.gateway import get_connection

from BACKEND.Postgres.Operations.users import errors as user_errors
from BACKEND.Postgres.Operations.users.create_user import create_user
from BACKEND.Postgres.Operations.users.get_user_by_id import get_user_by_id
from BACKEND.Postgres.Operations.users.get_user_by_email import get_user_by_email
from BACKEND.Postgres.Operations.users.get_user_auth_record_by_email import (
    get_user_auth_record_by_email,
)
from BACKEND.Postgres.Operations.users.list_users import list_users
from BACKEND.Postgres.Operations.users.update_user_profile import update_user_profile
from BACKEND.Postgres.Operations.users.update_user_password_hash import (
    update_user_password_hash,
)
from BACKEND.Postgres.Operations.users.update_user_status import update_user_status


class RollbackProbe(Exception):
    """Used to deliberately roll back a test transaction."""


class UsersOperationsIntegrationTests(unittest.TestCase):
    """Exercise each users operation against PostgreSQL."""

    @classmethod
    def setUpClass(cls) -> None:
        """Verify connectivity and ensure the expected schema exists."""
        with get_connection() as connection:
            with connection.cursor(row_factory=dict_row) as cursor:
                cursor.execute("SELECT current_database() AS database_name")
                row = cursor.fetchone()

                if row is None:
                    raise RuntimeError(
                        "Unable to determine the PostgreSQL database name."
                    )

                database_name = row["database_name"].lower()

                if any(
                    marker in database_name
                    for marker in ("prod", "production", "live")
                ):
                    raise RuntimeError(
                        "Refusing to run integration tests against a "
                        f"production-looking database: {database_name!r}."
                    )

                cursor.execute(
                    "SELECT to_regclass('public.users') AS users_table"
                )
                table_row = cursor.fetchone()

                if table_row is None or table_row["users_table"] is None:
                    raise RuntimeError(
                        "The public.users table was not found. Initialize "
                        "the OpsPilot schema before running these tests."
                    )

        print(
            f"\nConnected to PostgreSQL database: {database_name}"
        )

    def setUp(self) -> None:
        """Track only users created by the current test."""
        self.created_user_ids: list[UUID] = []
        self.test_marker = uuid4().hex

    def tearDown(self) -> None:
        """Delete test-owned records without truncating application tables."""
        if not self.created_user_ids:
            return

        with get_connection() as connection:
            with connection.cursor() as cursor:
                for user_id in self.created_user_ids:
                    cursor.execute(
                        "DELETE FROM users WHERE id = %s",
                        (user_id,),
                    )

    # ---------------------------------------------------------
    # Test data helpers
    # ---------------------------------------------------------

    def create_test_user(
        self,
        *,
        suffix: str = "primary",
        full_name: str | None = None,
        email: str | None = None,
        password_hash: str | None = None,
    ) -> dict[str, Any]:
        """Create a uniquely identified user through the real operation."""
        full_name = full_name or (
            f"OpsPilot Integration Test {self.test_marker} {suffix}"
        )
        email = email or (
            f"opspilot-test-{self.test_marker}-{suffix}@example.invalid"
        )
        password_hash = password_hash or (
            f"test-password-hash-{uuid4().hex}"
        )

        user = create_user(
            full_name=full_name,
            email=email,
            password_hash=password_hash,
        )

        self.assertIsInstance(user, dict)
        self.assertIn("id", user)

        user_id = UUID(str(user["id"]))
        self.created_user_ids.append(user_id)

        return {
            **user,
            "_test_password_hash": password_hash,
        }

    def fetch_user_from_database(
        self,
        user_id: UUID,
    ) -> dict[str, Any] | None:
        """Read the authoritative record directly from PostgreSQL."""
        with get_connection() as connection:
            with connection.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    """
                    SELECT
                        id,
                        full_name,
                        email,
                        password_hash,
                        account_status,
                        created_at,
                        updated_at
                    FROM users
                    WHERE id = %s;
                    """,
                    (user_id,),
                )
                row = cursor.fetchone()

        return dict(row) if row is not None else None

    @staticmethod
    def extract_user_rows(result: Any) -> list[dict[str, Any]]:
        """Normalize common list-result shapes without hiding bad results."""
        if isinstance(result, list):
            if not all(isinstance(item, dict) for item in result):
                raise AssertionError(
                    "The user list contains non-dictionary records."
                )
            return result

        if isinstance(result, tuple) and result:
            if isinstance(result[0], list):
                return UsersOperationsIntegrationTests.extract_user_rows(
                    result[0]
                )

        if isinstance(result, dict):
            # A single user record.
            if "id" in result and "email" in result:
                return [result]

            # A common paginated-list response shape.
            for key in (
                "users",
                "items",
                "records",
                "results",
                "data",
            ):
                value = result.get(key)

                if isinstance(value, list):
                    if not all(isinstance(item, dict) for item in value):
                        raise AssertionError(
                            f"The {key!r} collection contains invalid rows."
                        )
                    return value

                if isinstance(value, dict):
                    try:
                        return (
                            UsersOperationsIntegrationTests
                            .extract_user_rows(value)
                        )
                    except AssertionError:
                        continue

        raise AssertionError(
            "list_users returned an unexpected result shape: "
            f"{type(result).__name__}"
        )

    def assert_domain_exception(self, callback) -> Exception:
        """Require an operation-specific exception rather than a raw error."""
        try:
            callback()
        except Exception as exc:
            self.assertEqual(
                exc.__class__.__module__,
                user_errors.__name__,
                (
                    "Expected an exception defined in "
                    "BACKEND.Postgres.Operations.users.errors, but received "
                    f"{exc.__class__.__module__}.{exc.__class__.__name__}."
                ),
            )
            return exc

        self.fail("Expected a users-domain exception, but no error was raised.")

    # ---------------------------------------------------------
    # errors.py
    # ---------------------------------------------------------

    def test_users_error_module_is_importable(self) -> None:
        """Ensure domain-specific exception definitions are available."""
        self.assertTrue(
            any(
                isinstance(value, type)
                and issubclass(value, Exception)
                and value is not Exception
                for value in vars(user_errors).values()
            ),
            "users/errors.py should define domain-specific exceptions.",
        )

    # ---------------------------------------------------------
    # create_user.py
    # ---------------------------------------------------------

    def test_create_user_persists_record_without_exposing_hash(self) -> None:
        user = self.create_test_user()

        # The public operation result must not expose the password hash.
        self.assertNotIn("password_hash", user)

        # Verify the committed data directly in PostgreSQL.
        stored = self.fetch_user_from_database(UUID(str(user["id"])))

        self.assertIsNotNone(stored)
        assert stored is not None

        self.assertEqual(stored["full_name"], user["full_name"])
        self.assertEqual(stored["email"], user["email"])
        self.assertEqual(
            stored["password_hash"],
            user["_test_password_hash"],
        )
        self.assertEqual(stored["account_status"], "active")
        self.assertIsNotNone(stored["created_at"])
        self.assertIsNotNone(stored["updated_at"])

    def test_create_user_rejects_case_insensitive_duplicate_email(self) -> None:
        user = self.create_test_user()

        # The unique index applies to LOWER(email), so case changes must not
        # allow a second account for the same address.
        duplicate_email = user["email"].swapcase()

        with self.assertRaises(user_errors.UserAlreadyExistsError):
            create_user(
                full_name="Another Integration Test User",
                email=duplicate_email,
                password_hash=f"test-password-hash-{uuid4().hex}",
            )

        with get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT COUNT(*)
                    FROM users
                    WHERE LOWER(email) = LOWER(%s);
                    """,
                    (user["email"],),
                )
                count = cursor.fetchone()[0]

        self.assertEqual(
            count,
            1,
            "The case-insensitive email uniqueness rule was violated.",
        )

    def test_create_user_rejects_blank_full_name(self) -> None:
        email = (
            f"opspilot-invalid-{self.test_marker}@example.invalid"
        )

        with self.assertRaises(user_errors.InvalidUserRecordError):
            create_user(
                full_name="   ",
                email=email,
                password_hash=f"test-password-hash-{uuid4().hex}",
            )

        with get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT COUNT(*) FROM users WHERE email = %s",
                    (email,),
                )
                count = cursor.fetchone()[0]

        self.assertEqual(
            count,
            0,
            "A user with a whitespace-only name must not be persisted.",
        )

    # ---------------------------------------------------------
    # get_user_by_id.py
    # ---------------------------------------------------------

    def test_get_user_by_id_returns_public_user_record(self) -> None:
        user = self.create_test_user()

        result = get_user_by_id(UUID(str(user["id"])))

        self.assertIsNotNone(result)
        self.assertEqual(str(result["id"]), str(user["id"]))
        self.assertEqual(result["email"], user["email"])
        self.assertNotIn("password_hash", result)

    def test_get_user_by_id_returns_none_for_missing_user(self) -> None:
        missing_id = uuid4()

        result = get_user_by_id(missing_id)

        self.assertIsNone(result)

    # ---------------------------------------------------------
    # get_user_by_email.py
    # ---------------------------------------------------------

    def test_get_user_by_email_returns_public_record(self) -> None:
        user = self.create_test_user()

        result = get_user_by_email(user["email"])

        self.assertIsNotNone(result)
        self.assertEqual(str(result["id"]), str(user["id"]))
        self.assertEqual(result["email"], user["email"])
        self.assertNotIn("password_hash", result)

    def test_get_user_by_email_returns_none_for_missing_email(self) -> None:
        result = get_user_by_email(
            f"missing-{uuid4().hex}@example.invalid"
        )

        self.assertIsNone(result)

    # ---------------------------------------------------------
    # get_user_auth_record_by_email.py
    # ---------------------------------------------------------

    def test_auth_lookup_returns_password_hash_for_trusted_backend_use(
        self,
    ) -> None:
        user = self.create_test_user()

        result = get_user_auth_record_by_email(user["email"])

        self.assertIsNotNone(result)
        self.assertEqual(str(result["id"]), str(user["id"]))
        self.assertEqual(
            result["password_hash"],
            user["_test_password_hash"],
        )
        self.assertEqual(result["account_status"], "active")

    def test_auth_lookup_returns_none_for_missing_email(self) -> None:
        result = get_user_auth_record_by_email(
            f"missing-auth-{uuid4().hex}@example.invalid"
        )

        self.assertIsNone(result)

    # ---------------------------------------------------------
    # list_users.py
    # ---------------------------------------------------------

    def test_list_users_supports_search_and_bounded_pagination(
        self,
    ) -> None:
        marker = self.test_marker

        first = self.create_test_user(
            suffix="alpha",
            full_name=f"OpsPilot {marker} Alpha",
            email=f"{marker}-alpha@example.invalid",
        )
        second = self.create_test_user(
            suffix="beta",
            full_name=f"OpsPilot {marker} Beta",
            email=f"{marker}-beta@example.invalid",
        )

        first_page = self.extract_user_rows(
            list_users(search=marker, limit=1, offset=0)
        )
        second_page = self.extract_user_rows(
            list_users(search=marker, limit=1, offset=1)
        )

        self.assertEqual(
            len(first_page),
            1,
            "A page requested with limit=1 must return at most one row.",
        )
        self.assertEqual(
            len(second_page),
            1,
            "The second page should contain the other matching test user.",
        )

        first_page_id = str(first_page[0]["id"])
        second_page_id = str(second_page[0]["id"])

        self.assertNotEqual(
            first_page_id,
            second_page_id,
            "Pagination returned the same user on both pages.",
        )

        returned_ids = {first_page_id, second_page_id}
        expected_ids = {str(first["id"]), str(second["id"])}

        self.assertEqual(returned_ids, expected_ids)

        for row in first_page + second_page:
            self.assertNotIn(
                "password_hash",
                row,
                "list_users must not expose credential hashes.",
            )

    # ---------------------------------------------------------
    # update_user_profile.py
    # ---------------------------------------------------------

    def test_update_user_profile_persists_profile_changes(self) -> None:
        user = self.create_test_user()
        user_id = UUID(str(user["id"]))

        before = self.fetch_user_from_database(user_id)
        self.assertIsNotNone(before)
        assert before is not None

        new_name = f"Updated OpsPilot {self.test_marker}"
        new_email = (
            f"updated-{self.test_marker}@example.invalid"
        )

        update_user_profile(
            user_id=user_id,
            full_name=new_name,
            email=new_email,
        )

        stored = self.fetch_user_from_database(user_id)

        self.assertIsNotNone(stored)
        assert stored is not None

        self.assertEqual(stored["full_name"], new_name)
        self.assertEqual(stored["email"], new_email)
        self.assertGreaterEqual(
            stored["updated_at"],
            before["updated_at"],
            "updated_at must not move backwards after a profile change.",
        )

    def test_update_user_profile_rejects_duplicate_email(self) -> None:
        first = self.create_test_user(suffix="first")
        second = self.create_test_user(suffix="second")

        first_id = UUID(str(first["id"]))
        original_email = first["email"]

        with self.assertRaises(user_errors.UserAlreadyExistsError):
            update_user_profile(
                user_id=first_id,
                email=second["email"].swapcase(),
            )

        stored = self.fetch_user_from_database(first_id)

        self.assertIsNotNone(stored)
        assert stored is not None

        self.assertEqual(
            stored["email"],
            original_email,
            "A failed profile update must not alter the stored email.",
        )

    # ---------------------------------------------------------
    # update_user_password_hash.py
    # ---------------------------------------------------------

    def test_update_user_password_hash_persists_new_hash(self) -> None:
        user = self.create_test_user()
        user_id = UUID(str(user["id"]))

        old_hash = user["_test_password_hash"]
        new_hash = f"test-updated-password-hash-{uuid4().hex}"

        update_user_password_hash(
            user_id=user_id,
            password_hash=new_hash,
        )

        stored = self.fetch_user_from_database(user_id)

        self.assertIsNotNone(stored)
        assert stored is not None

        self.assertEqual(stored["password_hash"], new_hash)
        self.assertNotEqual(stored["password_hash"], old_hash)

        # Confirm the normal lookup does not expose the new hash.
        public_record = get_user_by_id(user_id)

        self.assertIsNotNone(public_record)
        self.assertNotIn("password_hash", public_record)

    # ---------------------------------------------------------
    # update_user_status.py
    # ---------------------------------------------------------

    def test_update_user_status_persists_valid_status_changes(self) -> None:
        user = self.create_test_user()
        user_id = UUID(str(user["id"]))

        for status in ("suspended", "deactivated", "active"):
            with self.subTest(status=status):
                update_user_status(
                    user_id=user_id,
                    account_status=status,
                )

                stored = self.fetch_user_from_database(user_id)

                self.assertIsNotNone(stored)
                assert stored is not None
                self.assertEqual(stored["account_status"], status)

    def test_update_user_status_rejects_invalid_status(self) -> None:
        user = self.create_test_user()
        user_id = UUID(str(user["id"]))

        self.assert_domain_exception(
            lambda: update_user_status(
                user_id=user_id,
                account_status="invalid-status",
            )
        )

        stored = self.fetch_user_from_database(user_id)

        self.assertIsNotNone(stored)
        assert stored is not None

        self.assertEqual(
            stored["account_status"],
            "active",
            "A rejected status update must leave the account unchanged.",
        )

    # ---------------------------------------------------------
    # Shared connection / transaction behaviour
    # ---------------------------------------------------------

    def test_create_user_respects_caller_owned_transaction(self) -> None:
        email = (
            f"opspilot-rollback-{self.test_marker}@example.invalid"
        )
        created_id: UUID | None = None

        # Deliberately fail after the operation returns but before the
        # caller-owned transaction commits.
        with self.assertRaises(RollbackProbe):
            with get_connection() as connection:
                user = create_user(
                    full_name=f"Rollback Test {self.test_marker}",
                    email=email,
                    password_hash=f"test-password-hash-{uuid4().hex}",
                    connection=connection,
                )

                created_id = UUID(str(user["id"]))
                self.created_user_ids.append(created_id)

                # The record should be visible inside this transaction.
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT COUNT(*) FROM users WHERE id = %s",
                        (created_id,),
                    )
                    self.assertEqual(cursor.fetchone()[0], 1)

                raise RollbackProbe("Force the caller's transaction to roll back.")

        self.assertIsNotNone(created_id)

        # After rollback, a separate connection must not see the record.
        with get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT COUNT(*) FROM users WHERE id = %s",
                    (created_id,),
                )
                count = cursor.fetchone()[0]

        self.assertEqual(
            count,
            0,
            "The operation committed a transaction owned by its caller.",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)