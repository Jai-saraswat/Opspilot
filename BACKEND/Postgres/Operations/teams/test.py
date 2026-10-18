"""Database integration tests for OpsPilot team Operations.

Run from the project root:
    python -m BACKEND.Postgres.Operations.teams.test

Tests use the configured PostgreSQL database. They create uniquely
identified test records and clean up only records created by this suite.

Never run integration tests against a production database.
"""

from __future__ import annotations

import unittest
from typing import Any
from uuid import UUID, uuid4

from psycopg.rows import dict_row

from BACKEND.Postgres.gateway import get_connection
from BACKEND.Postgres.Operations.teams import errors as team_errors
from BACKEND.Postgres.Operations.teams.create_team import create_team
from BACKEND.Postgres.Operations.teams.get_team_by_id import get_team_by_id
from BACKEND.Postgres.Operations.teams.get_team_by_name import get_team_by_name
from BACKEND.Postgres.Operations.teams.list_teams import list_teams
from BACKEND.Postgres.Operations.teams.update_team import update_team
from BACKEND.Postgres.Operations.teams.delete_team import delete_team


class RollbackProbe(Exception):
    """Force a caller-owned database transaction to roll back."""


class TeamsOperationsIntegrationTests(unittest.TestCase):
    """Exercise each teams operation against the real database."""

    @classmethod
    def setUpClass(cls) -> None:
        """Check database connectivity and required tables."""
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

                for table_name in ("users", "teams", "work_items"):
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
        """Prepare unique fixture data for each test."""
        self.marker = uuid4().hex
        self.created_user_ids: list[UUID] = []
        self.created_team_ids: list[UUID] = []
        self.created_work_item_ids: list[UUID] = []

        self.creator_id = self._create_test_user()

    def tearDown(self) -> None:
        """Remove only test-owned records, in FK-safe order."""
        with get_connection() as connection:
            with connection.cursor() as cursor:
                # Work items restrict deletion of their parent teams.
                for work_item_id in self.created_work_item_ids:
                    cursor.execute(
                        "DELETE FROM work_items WHERE id = %s",
                        (work_item_id,),
                    )

                # Team memberships and team-scoped permission overrides
                # are configured to cascade when their team is deleted.
                for team_id in self.created_team_ids:
                    cursor.execute(
                        "DELETE FROM teams WHERE id = %s",
                        (team_id,),
                    )

                # The test-created teams reference the creator in created_by,
                # so users are removed only after their teams.
                for user_id in self.created_user_ids:
                    cursor.execute(
                        "DELETE FROM users WHERE id = %s",
                        (user_id,),
                    )

    # =========================================================
    # TEST FIXTURES AND DATABASE HELPERS
    # =========================================================

    def _create_test_user(self) -> UUID:
        """Insert a disposable user needed by teams.created_by."""
        email = (
            f"team-test-{self.marker}@example.invalid"
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
                        f"Teams Test User {self.marker}",
                        email,
                        f"test-only-hash-{self.marker}",
                    ),
                )
                user_id = UUID(str(cursor.fetchone()[0]))

        self.created_user_ids.append(user_id)
        return user_id

    def _create_test_team(
        self,
        *,
        suffix: str = "primary",
        name: str | None = None,
        description: str | None = "Integration test team",
    ) -> dict[str, Any]:
        """Create a team through the actual Operations function."""
        name = name or f"OpsPilot Test {self.marker} {suffix}"

        team = create_team(
            name=name,
            description=description,
            created_by=self.creator_id,
        )

        self.assertIsInstance(team, dict)
        self.assertIn("id", team)

        team_id = UUID(str(team["id"]))
        self.created_team_ids.append(team_id)

        return team

    def _fetch_team(self, team_id: UUID) -> dict[str, Any] | None:
        """Read a team directly from PostgreSQL."""
        with get_connection() as connection:
            with connection.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    """
                    SELECT
                        id,
                        name,
                        description,
                        created_by,
                        created_at,
                        updated_at
                    FROM teams
                    WHERE id = %s;
                    """,
                    (team_id,),
                )
                row = cursor.fetchone()

        return dict(row) if row is not None else None

    def _fetch_team_count_by_name(self, name: str) -> int:
        """Verify uniqueness and persistence directly in the database."""
        with get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT COUNT(*) FROM teams WHERE name = %s;",
                    (name,),
                )
                return cursor.fetchone()[0]

    @staticmethod
    def _extract_team_rows(result: Any) -> list[dict[str, Any]]:
        """Normalize supported list-result shapes."""
        if isinstance(result, list):
            if not all(isinstance(row, dict) for row in result):
                raise AssertionError(
                    "list_teams returned non-dictionary rows."
                )
            return result

        if isinstance(result, tuple) and result:
            if isinstance(result[0], list):
                return TeamsOperationsIntegrationTests._extract_team_rows(
                    result[0]
                )

        if isinstance(result, dict):
            # A direct team record.
            if "id" in result and "name" in result:
                return [result]

            for key in ("teams", "items", "records", "results", "data"):
                value = result.get(key)

                if isinstance(value, list):
                    if not all(isinstance(row, dict) for row in value):
                        raise AssertionError(
                            f"list_teams returned invalid rows in {key!r}."
                        )
                    return value

                if isinstance(value, dict):
                    return (
                        TeamsOperationsIntegrationTests
                        ._extract_team_rows(value)
                    )

        raise AssertionError(
            "Unexpected list_teams return type: "
            f"{type(result).__name__}"
        )

    # =========================================================
    # errors.py
    # =========================================================

    def test_team_errors_module_exposes_domain_exceptions(self) -> None:
        """Check that the local team exception module is importable."""
        exception_types = [
            value
            for value in vars(team_errors).values()
            if isinstance(value, type)
            and issubclass(value, Exception)
            and value is not Exception
        ]

        self.assertGreater(
            len(exception_types),
            0,
            "teams/errors.py must define domain-specific exceptions.",
        )

    # =========================================================
    # create_team.py
    # =========================================================

    def test_create_team_persists_the_complete_team_record(self) -> None:
        team = self._create_test_team()

        self.assertEqual(
            team["name"],
            f"OpsPilot Test {self.marker} primary",
        )
        self.assertEqual(team["description"], "Integration test team")

        stored = self._fetch_team(UUID(str(team["id"])))

        self.assertIsNotNone(stored)
        assert stored is not None

        self.assertEqual(stored["name"], team["name"])
        self.assertEqual(stored["description"], team["description"])
        self.assertEqual(stored["created_by"], self.creator_id)
        self.assertIsNotNone(stored["created_at"])
        self.assertIsNotNone(stored["updated_at"])

    def test_create_team_rejects_duplicate_name(self) -> None:
        team = self._create_test_team()

        with self.assertRaises(team_errors.TeamAlreadyExistsError):
            create_team(
                name=team["name"],
                description="Duplicate team",
                created_by=self.creator_id,
            )

        self.assertEqual(
            self._fetch_team_count_by_name(team["name"]),
            1,
            "Duplicate team creation must not insert another row.",
        )

    def test_create_team_rejects_blank_name(self) -> None:
        blank_name = f"   {self.marker}   "

        # Use whitespace-only input to exercise chk_teams_name.
        with self.assertRaises(team_errors.InvalidTeamRecordError):
            create_team(
                name="   ",
                description="Invalid team",
                created_by=self.creator_id,
            )

        self.assertEqual(
            self._fetch_team_count_by_name(blank_name),
            0,
        )

    def test_create_team_rejects_nonexistent_creator(self) -> None:
        with self.assertRaises(team_errors.TeamCreatorNotFoundError):
            create_team(
                name=f"Missing Creator {self.marker}",
                description="This team must not persist",
                created_by=uuid4(),
            )

        self.assertEqual(
            self._fetch_team_count_by_name(
                f"Missing Creator {self.marker}"
            ),
            0,
        )

    # =========================================================
    # get_team_by_id.py
    # =========================================================

    def test_get_team_by_id_returns_persisted_team(self) -> None:
        team = self._create_test_team()

        result = get_team_by_id(UUID(str(team["id"])))

        self.assertIsNotNone(result)
        self.assertEqual(str(result["id"]), str(team["id"]))
        self.assertEqual(result["name"], team["name"])
        self.assertEqual(result["created_by"], self.creator_id)

    def test_get_team_by_id_returns_none_for_missing_team(self) -> None:
        result = get_team_by_id(uuid4())
        self.assertIsNone(result)

    # =========================================================
    # get_team_by_name.py
    # =========================================================

    def test_get_team_by_name_returns_matching_team(self) -> None:
        team = self._create_test_team()

        result = get_team_by_name(team["name"])

        self.assertIsNotNone(result)
        self.assertEqual(str(result["id"]), str(team["id"]))
        self.assertEqual(result["name"], team["name"])

    def test_get_team_by_name_returns_none_for_missing_name(self) -> None:
        result = get_team_by_name(
            f"Missing Team {uuid4().hex}"
        )

        self.assertIsNone(result)

    # =========================================================
    # list_teams.py
    # =========================================================

    def test_list_teams_supports_search_and_pagination(self) -> None:
        first = self._create_test_team(
            suffix="alpha",
            name=f"OpsPilot Search {self.marker} Alpha",
        )
        second = self._create_test_team(
            suffix="beta",
            name=f"OpsPilot Search {self.marker} Beta",
        )

        page_one = self._extract_team_rows(
            list_teams(
                search=self.marker,
                limit=1,
                offset=0,
            )
        )
        page_two = self._extract_team_rows(
            list_teams(
                search=self.marker,
                limit=1,
                offset=1,
            )
        )

        self.assertEqual(len(page_one), 1)
        self.assertEqual(len(page_two), 1)

        first_page_id = str(page_one[0]["id"])
        second_page_id = str(page_two[0]["id"])

        self.assertNotEqual(
            first_page_id,
            second_page_id,
            "Pagination returned the same team on both pages.",
        )

        self.assertEqual(
            {first_page_id, second_page_id},
            {str(first["id"]), str(second["id"])},
        )

    def test_list_teams_does_not_return_unrelated_teams_for_search(
        self,
    ) -> None:
        team = self._create_test_team()

        rows = self._extract_team_rows(
            list_teams(
                search=f"no-match-{uuid4().hex}",
                limit=10,
                offset=0,
            )
        )

        self.assertNotIn(
            str(team["id"]),
            {str(row["id"]) for row in rows},
        )

    # =========================================================
    # update_team.py
    # =========================================================

    def test_update_team_persists_name_and_description(self) -> None:
        team = self._create_test_team()
        team_id = UUID(str(team["id"]))

        before = self._fetch_team(team_id)
        self.assertIsNotNone(before)
        assert before is not None

        new_name = f"Updated Team {self.marker}"
        new_description = "Updated by integration test"

        update_team(
            team_id=team_id,
            name=new_name,
            description=new_description,
        )

        stored = self._fetch_team(team_id)

        self.assertIsNotNone(stored)
        assert stored is not None

        self.assertEqual(stored["name"], new_name)
        self.assertEqual(stored["description"], new_description)
        self.assertGreaterEqual(
            stored["updated_at"],
            before["updated_at"],
        )

    def test_update_team_can_clear_description(self) -> None:
        team = self._create_test_team(
            description="Description to clear"
        )

        team_id = UUID(str(team["id"]))

        update_team(
            team_id=team_id,
            description=None,
        )

        stored = self._fetch_team(team_id)

        self.assertIsNotNone(stored)
        assert stored is not None
        self.assertIsNone(stored["description"])

    def test_update_team_leaves_omitted_fields_unchanged(self) -> None:
        team = self._create_test_team(
            description="Keep this description"
        )

        team_id = UUID(str(team["id"]))

        update_team(
            team_id=team_id,
            name=f"Renamed Only {self.marker}",
        )

        stored = self._fetch_team(team_id)

        self.assertIsNotNone(stored)
        assert stored is not None

        self.assertEqual(
            stored["name"],
            f"Renamed Only {self.marker}",
        )
        self.assertEqual(
            stored["description"],
            "Keep this description",
        )

    def test_update_team_rejects_duplicate_name_without_changes(
        self,
    ) -> None:
        first = self._create_test_team(suffix="first")
        second = self._create_test_team(suffix="second")

        second_id = UUID(str(second["id"]))
        original_name = second["name"]
        original_description = second["description"]

        with self.assertRaises(team_errors.TeamAlreadyExistsError):
            update_team(
                team_id=second_id,
                name=first["name"],
            )

        stored = self._fetch_team(second_id)

        self.assertIsNotNone(stored)
        assert stored is not None

        self.assertEqual(stored["name"], original_name)
        self.assertEqual(
            stored["description"],
            original_description,
        )

    def test_update_team_rejects_blank_name(self) -> None:
        team = self._create_test_team()
        team_id = UUID(str(team["id"]))
        original_name = team["name"]

        with self.assertRaises(team_errors.InvalidTeamRecordError):
            update_team(
                team_id=team_id,
                name="   ",
            )

        stored = self._fetch_team(team_id)

        self.assertIsNotNone(stored)
        assert stored is not None
        self.assertEqual(stored["name"], original_name)

    # =========================================================
    # delete_team.py
    # =========================================================

    def test_delete_team_removes_team_record(self) -> None:
        team = self._create_test_team()
        team_id = UUID(str(team["id"]))

        delete_team(team_id=team_id)

        stored = self._fetch_team(team_id)

        self.assertIsNone(
            stored,
            "delete_team should remove the requested team.",
        )

        # Prevent redundant cleanup of an already deleted team.
        self.created_team_ids.remove(team_id)

    def test_delete_team_rejects_team_referenced_by_work_item(
        self,
    ) -> None:
        team = self._create_test_team()
        team_id = UUID(str(team["id"]))

        with get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO work_items (
                        title,
                        description,
                        type,
                        team_id,
                        created_by
                    )
                    VALUES (%s, %s, %s, %s, %s)
                    RETURNING id;
                    """,
                    (
                        f"Test work item {self.marker}",
                        "Temporary row used to validate team deletion.",
                        "investigation",
                        team_id,
                        self.creator_id,
                    ),
                )
                work_item_id = UUID(str(cursor.fetchone()[0]))

        self.created_work_item_ids.append(work_item_id)

        with self.assertRaises(team_errors.TeamInUseError):
            delete_team(team_id=team_id)

        stored = self._fetch_team(team_id)

        self.assertIsNotNone(
            stored,
            "A team referenced by a work item must not be deleted.",
        )

    def test_delete_team_respects_caller_owned_transaction(self) -> None:
        team = self._create_test_team()
        team_id = UUID(str(team["id"]))

        with self.assertRaises(RollbackProbe):
            with get_connection() as connection:
                delete_team(
                    team_id=team_id,
                    connection=connection,
                )

                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT COUNT(*) FROM teams WHERE id = %s",
                        (team_id,),
                    )
                    self.assertEqual(cursor.fetchone()[0], 0)

                raise RollbackProbe(
                    "Force rollback of the caller-owned transaction."
                )

        # The outer transaction rolled back, restoring the deleted row.
        stored = self._fetch_team(team_id)
        self.assertIsNotNone(
            stored,
            "delete_team committed a transaction owned by its caller.",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)