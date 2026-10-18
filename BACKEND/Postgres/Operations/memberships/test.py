"""Database integration tests for OpsPilot membership Operations.

Run from the project root:
    python -m BACKEND.Postgres.Operations.memberships.test

These tests use real PostgreSQL records. Each test creates unique fixtures
and removes only those fixtures during cleanup.

Never run integration tests against a production database.
"""

from __future__ import annotations

import unittest
from typing import Any
from uuid import UUID, uuid4

from psycopg.rows import dict_row

from BACKEND.Postgres.gateway import get_connection
from BACKEND.Postgres.Operations.memberships import errors as membership_errors
from BACKEND.Postgres.Operations.memberships.add_team_member import (
    add_team_member,
)
from BACKEND.Postgres.Operations.memberships.get_membership import (
    get_membership,
)
from BACKEND.Postgres.Operations.memberships.list_team_members import (
    list_team_members,
)
from BACKEND.Postgres.Operations.memberships.list_user_teams import (
    list_user_teams,
)
from BACKEND.Postgres.Operations.memberships.update_membership_role import (
    update_membership_role,
)
from BACKEND.Postgres.Operations.memberships.remove_team_member import (
    remove_team_member,
)


class RollbackProbe(Exception):
    """Force a caller-owned transaction to roll back."""


class MembershipsOperationsIntegrationTests(unittest.TestCase):
    """Validate membership operations against PostgreSQL."""

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
                        "Refusing to run integration tests against a "
                        "production-looking database: "
                        f"{cls.database_name!r}"
                    )

                for table_name in (
                    "users",
                    "teams",
                    "team_memberships",
                ):
                    cursor.execute(
                        "SELECT to_regclass(%s) AS table_name",
                        (f"public.{table_name}",),
                    )
                    result = cursor.fetchone()

                    if result is None or result["table_name"] is None:
                        raise RuntimeError(
                            f"Required table public.{table_name} was not "
                            "found. Initialize the OpsPilot schema first."
                        )

        print(
            f"\nConnected to PostgreSQL database: {cls.database_name}"
        )

    def setUp(self) -> None:
        """Create isolated users and teams for each test."""
        self.marker = uuid4().hex
        self.created_user_ids: list[UUID] = []
        self.created_team_ids: list[UUID] = []

        self.user_a = self._create_test_user("creator")
        self.user_b = self._create_test_user("member")

        self.team_a = self._create_test_team("alpha")
        self.team_b = self._create_test_team("beta")

    def tearDown(self) -> None:
        """Remove test-owned teams and users, preserving other data."""
        with get_connection() as connection:
            with connection.cursor() as cursor:
                # team_memberships has ON DELETE CASCADE from teams.
                for team_id in self.created_team_ids:
                    cursor.execute(
                        "DELETE FROM teams WHERE id = %s",
                        (team_id,),
                    )

                # Each test team references its creator through created_by.
                for user_id in self.created_user_ids:
                    cursor.execute(
                        "DELETE FROM users WHERE id = %s",
                        (user_id,),
                    )

    # =========================================================
    # FIXTURE HELPERS
    # =========================================================

    def _create_test_user(self, suffix: str) -> UUID:
        """Insert a disposable user required by the foreign keys."""
        email = (
            f"membership-test-{self.marker}-{suffix}@example.invalid"
        )

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
                        f"Membership Test {suffix} {self.marker}",
                        email,
                        f"test-only-hash-{uuid4().hex}",
                    ),
                )
                user_id = UUID(str(cursor.fetchone()[0]))

        self.created_user_ids.append(user_id)
        return user_id

    def _create_test_team(self, suffix: str) -> UUID:
        """Insert a disposable team directly for test setup."""
        name = f"Membership Test Team {self.marker} {suffix}"

        with get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO teams (
                        name,
                        description,
                        created_by
                    )
                    VALUES (%s, %s, %s)
                    RETURNING id;
                    """,
                    (
                        name,
                        "Temporary membership integration-test team.",
                        self.user_a,
                    ),
                )
                team_id = UUID(str(cursor.fetchone()[0]))

        self.created_team_ids.append(team_id)
        return team_id

    def _fetch_membership(
        self,
        team_id: UUID,
        user_id: UUID,
    ) -> dict[str, Any] | None:
        """Read the authoritative membership row directly from PostgreSQL."""
        with get_connection() as connection:
            with connection.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    """
                    SELECT
                        id,
                        team_id,
                        user_id,
                        role,
                        joined_at
                    FROM team_memberships
                    WHERE team_id = %s
                      AND user_id = %s;
                    """,
                    (team_id, user_id),
                )
                row = cursor.fetchone()

        return dict(row) if row is not None else None

    def _fetch_membership_count(
        self,
        team_id: UUID,
        user_id: UUID,
    ) -> int:
        """Count relationship rows to verify uniqueness."""
        with get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT COUNT(*)
                    FROM team_memberships
                    WHERE team_id = %s
                      AND user_id = %s;
                    """,
                    (team_id, user_id),
                )
                return cursor.fetchone()[0]

    @staticmethod
    def _extract_rows(result: Any) -> list[dict[str, Any]]:
        """Normalize list results without silently accepting invalid data."""
        if isinstance(result, list):
            if not all(isinstance(row, dict) for row in result):
                raise AssertionError(
                    "The operation returned non-dictionary list entries."
                )
            return result

        if isinstance(result, tuple) and result:
            if isinstance(result[0], list):
                return (
                    MembershipsOperationsIntegrationTests
                    ._extract_rows(result[0])
                )

        if isinstance(result, dict):
            # Allow a single membership/team result as well as paginated data.
            if (
                "team_id" in result
                or ("id" in result and "user_id" in result)
            ):
                return [result]

            for key in (
                "members",
                "memberships",
                "teams",
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
                        MembershipsOperationsIntegrationTests
                        ._extract_rows(value)
                    )

        raise AssertionError(
            "Unexpected list operation result type: "
            f"{type(result).__name__}"
        )

    # =========================================================
    # errors.py
    # =========================================================

    def test_membership_errors_module_exposes_domain_exceptions(
        self,
    ) -> None:
        """Verify membership-specific exception definitions are available."""
        exception_types = [
            value
            for value in vars(membership_errors).values()
            if isinstance(value, type)
            and issubclass(value, Exception)
            and value is not Exception
        ]

        self.assertGreater(
            len(exception_types),
            0,
            "memberships/errors.py must define domain-specific exceptions.",
        )

    # =========================================================
    # add_team_member.py
    # =========================================================

    def test_add_team_member_persists_membership(self) -> None:
        result = add_team_member(
            team_id=self.team_a,
            user_id=self.user_b,
            role="member",
        )

        self.assertIsNotNone(result)

        stored = self._fetch_membership(
            self.team_a,
            self.user_b,
        )

        self.assertIsNotNone(stored)
        assert stored is not None

        self.assertEqual(stored["team_id"], self.team_a)
        self.assertEqual(stored["user_id"], self.user_b)
        self.assertEqual(stored["role"], "member")
        self.assertIsNotNone(stored["joined_at"])

    def test_add_team_member_supports_valid_roles(self) -> None:
        for role in ("lead", "member", "approver"):
            with self.subTest(role=role):
                user_id = self._create_test_user(f"role-{role}")

                result = add_team_member(
                    team_id=self.team_a,
                    user_id=user_id,
                    role=role,
                )

                self.assertIsNotNone(result)

                stored = self._fetch_membership(
                    self.team_a,
                    user_id,
                )

                self.assertIsNotNone(stored)
                assert stored is not None
                self.assertEqual(stored["role"], role)

    def test_add_team_member_rejects_duplicate_membership(self) -> None:
        add_team_member(
            team_id=self.team_a,
            user_id=self.user_b,
            role="member",
        )

        with self.assertRaises(
            membership_errors.MembershipAlreadyExistsError
        ):
            add_team_member(
                team_id=self.team_a,
                user_id=self.user_b,
                role="approver",
            )

        self.assertEqual(
            self._fetch_membership_count(self.team_a, self.user_b),
            1,
            "A duplicate team/user pair must not be inserted.",
        )

        stored = self._fetch_membership(
            self.team_a,
            self.user_b,
        )
        self.assertIsNotNone(stored)
        assert stored is not None
        self.assertEqual(
            stored["role"],
            "member",
            "A rejected duplicate insert must not change the original role.",
        )

    def test_add_team_member_rejects_invalid_role(self) -> None:
        with self.assertRaises(
            membership_errors.InvalidMembershipRecordError
        ):
            add_team_member(
                team_id=self.team_a,
                user_id=self.user_b,
                role="owner",
            )

        self.assertIsNone(
            self._fetch_membership(self.team_a, self.user_b),
            "An invalid membership role must not be persisted.",
        )

    def test_add_team_member_rejects_missing_related_record(self) -> None:
        with self.assertRaises(
            membership_errors.MembershipRelatedRecordNotFoundError
        ):
            add_team_member(
                team_id=self.team_a,
                user_id=uuid4(),
                role="member",
            )

        self.assertEqual(
            self._fetch_membership_count(self.team_a, uuid4()),
            0,
        )

    # =========================================================
    # get_membership.py
    # =========================================================

    def test_get_membership_returns_existing_relationship(self) -> None:
        add_team_member(
            team_id=self.team_a,
            user_id=self.user_b,
            role="approver",
        )

        result = get_membership(
            team_id=self.team_a,
            user_id=self.user_b,
        )

        self.assertIsNotNone(result)
        self.assertEqual(result["team_id"], self.team_a)
        self.assertEqual(result["user_id"], self.user_b)
        self.assertEqual(result["role"], "approver")

    def test_get_membership_returns_none_for_missing_relationship(
        self,
    ) -> None:
        result = get_membership(
            team_id=self.team_a,
            user_id=self.user_b,
        )

        self.assertIsNone(result)

    # =========================================================
    # list_team_members.py
    # =========================================================

    def test_list_team_members_returns_only_the_requested_team(
        self,
    ) -> None:
        add_team_member(
            team_id=self.team_a,
            user_id=self.user_a,
            role="lead",
        )
        add_team_member(
            team_id=self.team_a,
            user_id=self.user_b,
            role="member",
        )

        # A membership in another team must not appear in this result.
        add_team_member(
            team_id=self.team_b,
            user_id=self.user_b,
            role="approver",
        )

        rows = self._extract_rows(
            list_team_members(
                team_id=self.team_a,
                limit=50,
                offset=0,
            )
        )

        returned_user_ids = {
            str(row["user_id"])
            for row in rows
        }

        self.assertEqual(
            returned_user_ids,
            {str(self.user_a), str(self.user_b)},
        )

        self.assertTrue(
            all(str(row["team_id"]) == str(self.team_a) for row in rows),
            "list_team_members returned a row for another team.",
        )

    def test_list_team_members_supports_search_and_pagination(
        self,
    ) -> None:
        # Create three uniquely named members so search cannot match other
        # test records from this suite.
        user_ids = [
            self._create_test_user(f"search-{index}")
            for index in range(3)
        ]

        for user_id in user_ids:
            add_team_member(
                team_id=self.team_a,
                user_id=user_id,
                role="member",
            )

        search_term = f"search-{self.marker}"

        # The usernames contain "search-{index}", whereas the unique marker
        # is included in the full name and email of each fixture.
        page_one = self._extract_rows(
            list_team_members(
                team_id=self.team_a,
                search=self.marker,
                limit=1,
                offset=0,
            )
        )
        page_two = self._extract_rows(
            list_team_members(
                team_id=self.team_a,
                search=self.marker,
                limit=1,
                offset=1,
            )
        )

        self.assertEqual(len(page_one), 1)
        self.assertEqual(len(page_two), 1)

        self.assertNotEqual(
            str(page_one[0]["user_id"]),
            str(page_two[0]["user_id"]),
            "Pagination returned the same member on both pages.",
        )

        returned_ids = {
            str(page_one[0]["user_id"]),
            str(page_two[0]["user_id"]),
        }

        self.assertTrue(
            returned_ids.issubset({str(user_id) for user_id in user_ids}),
            f"Search returned unexpected users for {search_term!r}.",
        )

    # =========================================================
    # list_user_teams.py
    # =========================================================

    def test_list_user_teams_returns_all_teams_for_user(self) -> None:
        add_team_member(
            team_id=self.team_a,
            user_id=self.user_b,
            role="member",
        )
        add_team_member(
            team_id=self.team_b,
            user_id=self.user_b,
            role="approver",
        )

        rows = self._extract_rows(
            list_user_teams(
                user_id=self.user_b,
                limit=50,
                offset=0,
            )
        )

        returned_team_ids = {
            str(row["id"])
            for row in rows
        }

        self.assertEqual(
            returned_team_ids,
            {str(self.team_a), str(self.team_b)},
        )

        # Verify that the memberships and roles were persisted correctly.
        # Role is checked against the membership table because list_user_teams()
        # does not currently include role in its returned team records.
        membership_a = self._fetch_membership(self.team_a, self.user_b)
        membership_b = self._fetch_membership(self.team_b, self.user_b)

        self.assertIsNotNone(membership_a)
        self.assertIsNotNone(membership_b)

        assert membership_a is not None
        assert membership_b is not None

        self.assertEqual(membership_a["role"], "member")
        self.assertEqual(membership_b["role"], "approver")

    def test_list_user_teams_returns_empty_for_user_without_memberships(
        self,
    ) -> None:
        result = list_user_teams(
            user_id=self.user_b,
            limit=50,
            offset=0,
        )

        rows = self._extract_rows(result)

        self.assertEqual(rows, [])

    # =========================================================
    # update_membership_role.py
    # =========================================================

    def test_update_membership_role_persists_role_change(self) -> None:
        add_team_member(
            team_id=self.team_a,
            user_id=self.user_b,
            role="member",
        )

        update_membership_role(
            team_id=self.team_a,
            user_id=self.user_b,
            role="approver",
        )

        stored = self._fetch_membership(
            self.team_a,
            self.user_b,
        )

        self.assertIsNotNone(stored)
        assert stored is not None
        self.assertEqual(stored["role"], "approver")

    def test_update_membership_role_rejects_invalid_role(self) -> None:
        add_team_member(
            team_id=self.team_a,
            user_id=self.user_b,
            role="member",
        )

        with self.assertRaises(
            membership_errors.InvalidMembershipRecordError
        ):
            update_membership_role(
                team_id=self.team_a,
                user_id=self.user_b,
                role="administrator",
            )

        stored = self._fetch_membership(
            self.team_a,
            self.user_b,
        )

        self.assertIsNotNone(stored)
        assert stored is not None
        self.assertEqual(
            stored["role"],
            "member",
            "An invalid role change must leave the original role intact.",
        )

    def test_update_membership_role_does_not_create_missing_membership(
        self,
    ) -> None:
        result = update_membership_role(
            team_id=self.team_a,
            user_id=self.user_b,
            role="approver",
        )

        self.assertIsNone(result)
        self.assertIsNone(
            self._fetch_membership(self.team_a, self.user_b)
        )

    # =========================================================
    # remove_team_member.py
    # =========================================================

    def test_remove_team_member_removes_existing_relationship(self) -> None:
        add_team_member(
            team_id=self.team_a,
            user_id=self.user_b,
            role="member",
        )

        result = remove_team_member(
            team_id=self.team_a,
            user_id=self.user_b,
        )

        self.assertTrue(result)
        self.assertIsNone(
            self._fetch_membership(self.team_a, self.user_b)
        )

    def test_remove_team_member_returns_false_when_missing(
        self,
    ) -> None:
        result = remove_team_member(
            team_id=self.team_a,
            user_id=self.user_b,
        )

        self.assertFalse(result)

    def test_remove_team_member_does_not_affect_other_team_membership(
        self,
    ) -> None:
        add_team_member(
            team_id=self.team_a,
            user_id=self.user_b,
            role="member",
        )
        add_team_member(
            team_id=self.team_b,
            user_id=self.user_b,
            role="approver",
        )

        removed = remove_team_member(
            team_id=self.team_a,
            user_id=self.user_b,
        )

        self.assertTrue(removed)

        self.assertIsNone(
            self._fetch_membership(self.team_a, self.user_b)
        )

        remaining = self._fetch_membership(
            self.team_b,
            self.user_b,
        )

        self.assertIsNotNone(remaining)
        assert remaining is not None
        self.assertEqual(remaining["role"], "approver")

    # =========================================================
    # CALLER-OWNED TRANSACTION
    # =========================================================

    def test_add_team_member_respects_caller_owned_transaction(
        self,
    ) -> None:
        with self.assertRaises(RollbackProbe):
            with get_connection() as connection:
                add_team_member(
                    team_id=self.team_a,
                    user_id=self.user_b,
                    role="member",
                    connection=connection,
                )

                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT COUNT(*)
                        FROM team_memberships
                        WHERE team_id = %s
                          AND user_id = %s;
                        """,
                        (self.team_a, self.user_b),
                    )

                    self.assertEqual(cursor.fetchone()[0], 1)

                raise RollbackProbe(
                    "Force caller-owned membership transaction rollback."
                )

        self.assertIsNone(
            self._fetch_membership(self.team_a, self.user_b),
            "add_team_member committed a transaction owned by its caller.",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)