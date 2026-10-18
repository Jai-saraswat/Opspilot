
"""PostgreSQL integration tests for team Services.

Run from the project root:
    python -m BACKEND.Services.teams.test

These tests use the configured PostgreSQL database and create disposable
records. Never run them against production.
"""

from __future__ import annotations

import unittest
from uuid import UUID, uuid4

from psycopg.rows import dict_row

from BACKEND.Postgres.gateway import get_connection
from BACKEND.Services.teams.create_team import create_team
from BACKEND.Services.teams.get_team_by_id import get_team_by_id
from BACKEND.Services.teams.get_team_by_name import get_team_by_name
from BACKEND.Services.teams.list_teams import list_teams
from BACKEND.Services.teams.update_team import update_team
from BACKEND.Services.teams.delete_team import delete_team


def data_of(response):
    """Return successful ServiceResponse data or fail with diagnostics."""
    if not getattr(response, "success", False):
        raise AssertionError(
            f"Expected success; status={getattr(response, 'http_status', None)}, "
            f"error={getattr(response, 'error', None)!r}"
        )
    return response.outputs.data


def assert_failure(test, response, expected_status=None):
    test.assertFalse(response.success, "Expected the service call to fail.")
    if expected_status is not None:
        test.assertEqual(response.http_status, expected_status)


class TeamServicesIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with get_connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute("SELECT current_database() AS db")
                cls.database_name = cur.fetchone()["db"]

                if any(
                    marker in cls.database_name.lower()
                    for marker in ("prod", "production", "live")
                ):
                    raise RuntimeError(
                        f"Refusing to run against production-looking database "
                        f"{cls.database_name!r}"
                    )

                for table in ("users", "teams", "team_memberships"):
                    cur.execute(
                        "SELECT to_regclass(%s) AS table_name",
                        (f"public.{table}",),
                    )
                    if cur.fetchone()["table_name"] is None:
                        raise RuntimeError(f"Missing table public.{table}")

        print(f"\nTeam Service tests using database: {cls.database_name}")

    def setUp(self):
        self.marker = uuid4().hex
        self.user_ids = []
        self.team_ids = []
        self.actor_id = self._create_user("actor")

    def tearDown(self):
        # Delete only records created by this test. Memberships cascade
        # when their team is deleted; teams reference their creator.
        with get_connection() as conn:
            with conn.cursor() as cur:
                for team_id in self.team_ids:
                    cur.execute("DELETE FROM teams WHERE id = %s", (team_id,))
                for user_id in self.user_ids:
                    cur.execute("DELETE FROM users WHERE id = %s", (user_id,))

    def _create_user(self, label):
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO users (full_name, email, password_hash)
                    VALUES (%s, %s, %s)
                    RETURNING id
                    """,
                    (
                        f"Team test {label} {self.marker}",
                        f"team-{label}-{self.marker}@example.invalid",
                        f"test-hash-{self.marker}",
                    ),
                )
                user_id = UUID(str(cur.fetchone()[0]))

        self.user_ids.append(user_id)
        return user_id

    def _create_team(self, suffix="primary", description="Test description"):
        name = f"Team Service {self.marker} {suffix}"
        response = create_team(
            actor_user_id=self.actor_id,
            name=name,
            description=description,
        )
        team = data_of(response)["team"]
        team_id = UUID(str(team["id"]))
        self.team_ids.append(team_id)
        return team

    def _fetch_team(self, team_id):
        with get_connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    SELECT id, name, description, created_by,
                           created_at, updated_at
                    FROM teams
                    WHERE id = %s
                    """,
                    (UUID(str(team_id)),),
                )
                return cur.fetchone()

    def _fetch_membership(self, team_id, user_id):
        with get_connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    SELECT id, team_id, user_id, role, joined_at
                    FROM team_memberships
                    WHERE team_id = %s AND user_id = %s
                    """,
                    (UUID(str(team_id)), UUID(str(user_id))),
                )
                return cur.fetchone()

    def test_create_team_persists_team_and_creator_lead(self):
        team = self._create_team()
        stored = self._fetch_team(team["id"])
        membership = self._fetch_membership(team["id"], self.actor_id)

        self.assertIsNotNone(stored)
        self.assertEqual(stored["name"], team["name"])
        self.assertEqual(stored["description"], "Test description")
        self.assertEqual(UUID(str(stored["created_by"])), self.actor_id)

        self.assertIsNotNone(membership)
        self.assertEqual(membership["role"], "lead")

    def test_duplicate_team_name_does_not_create_second_team(self):
        team = self._create_team()
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) FROM teams WHERE name = %s",
                    (team["name"],),
                )
                before = cur.fetchone()[0]

        response = create_team(
            actor_user_id=self.actor_id,
            name=team["name"],
            description="Duplicate attempt",
        )
        assert_failure(self, response, 409)

        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) FROM teams WHERE name = %s",
                    (team["name"],),
                )
                after = cur.fetchone()[0]

        self.assertEqual(before, 1)
        self.assertEqual(after, 1)

    def test_get_team_by_id_matches_database(self):
        team = self._create_team()

        response = get_team_by_id(
            actor_user_id=self.actor_id,
            team_id=team["id"],
        )
        returned = data_of(response)["team"]
        stored = self._fetch_team(team["id"])

        self.assertIsNotNone(stored)
        self.assertEqual(str(returned["id"]), str(stored["id"]))
        self.assertEqual(returned["name"], stored["name"])
        self.assertEqual(returned["description"], stored["description"])

    def test_get_team_by_name_matches_database(self):
        team = self._create_team()

        response = get_team_by_name(
            actor_user_id=self.actor_id,
            name=team["name"],
        )
        returned = data_of(response)["team"]
        stored = self._fetch_team(team["id"])

        self.assertIsNotNone(stored)
        self.assertEqual(str(returned["id"]), str(stored["id"]))
        self.assertEqual(returned["name"], stored["name"])

    def test_list_teams_returns_database_backed_results(self):
        first = self._create_team("list-a")
        second = self._create_team("list-b")

        response = list_teams(
            actor_user_id=self.actor_id,
            limit=50,
            offset=0,
            search=self.marker,
        )
        result = data_of(response)

        self.assertGreaterEqual(result["total"], 2)
        returned_ids = {str(item["id"]) for item in result["items"]}
        self.assertIn(str(first["id"]), returned_ids)
        self.assertIn(str(second["id"]), returned_ids)

        # Independently verify the matching records in PostgreSQL.
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT COUNT(*)
                    FROM teams
                    WHERE created_by = %s
                      AND name LIKE %s
                    """,
                    (self.actor_id, f"%{self.marker}%"),
                )
                db_count = cur.fetchone()[0]

        self.assertEqual(db_count, 2)

    def test_list_teams_pagination_is_respected(self):
        first = self._create_team("page-a")
        second = self._create_team("page-b")

        page_one = data_of(
            list_teams(
                actor_user_id=self.actor_id,
                limit=1,
                offset=0,
                search=self.marker,
            )
        )
        page_two = data_of(
            list_teams(
                actor_user_id=self.actor_id,
                limit=1,
                offset=1,
                search=self.marker,
            )
        )

        self.assertEqual(len(page_one["items"]), 1)
        self.assertEqual(len(page_two["items"]), 1)
        self.assertEqual(page_one["total"], 2)
        self.assertEqual(page_two["total"], 2)
        self.assertNotEqual(
            str(page_one["items"][0]["id"]),
            str(page_two["items"][0]["id"]),
        )
        self.assertEqual(
            {str(page_one["items"][0]["id"]), str(page_two["items"][0]["id"])},
            {str(first["id"]), str(second["id"])},
        )

    def test_update_team_persists_rename_and_description_clear(self):
        team = self._create_team()

        new_name = f"Renamed {self.marker}"
        response = update_team(
            actor_user_id=self.actor_id,
            team_id=team["id"],
            name=new_name,
            description=None,
        )
        returned = data_of(response)["team"]
        stored = self._fetch_team(team["id"])

        self.assertIsNotNone(stored)
        self.assertEqual(returned["name"], new_name)
        self.assertIsNone(returned["description"])
        self.assertEqual(stored["name"], new_name)
        self.assertIsNone(stored["description"])

        # The previous name must no longer resolve to a database record.
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id FROM teams WHERE name = %s",
                    (team["name"],),
                )
                self.assertIsNone(cur.fetchone())

    def test_empty_update_is_rejected_without_changing_database(self):
        team = self._create_team()
        before = self._fetch_team(team["id"])

        response = update_team(
            actor_user_id=self.actor_id,
            team_id=team["id"],
        )
        assert_failure(self, response, 400)

        after = self._fetch_team(team["id"])
        self.assertEqual(after["name"], before["name"])
        self.assertEqual(after["description"], before["description"])

    def test_invalid_team_id_is_rejected_without_database_change(self):
        before = len(self.team_ids)
        response = get_team_by_id(
            actor_user_id=self.actor_id,
            team_id="not-a-uuid",
        )

        assert_failure(self, response, 400)
        self.assertEqual(len(self.team_ids), before)

    def test_invalid_pagination_is_rejected(self):
        response = list_teams(
            actor_user_id=self.actor_id,
            limit=0,
            offset=0,
        )
        assert_failure(self, response, 400)

    def test_delete_team_removes_team_and_memberships(self):
        team = self._create_team()
        team_id = UUID(str(team["id"]))

        # Confirm the creator membership exists before deletion.
        self.assertIsNotNone(
            self._fetch_membership(team_id, self.actor_id)
        )

        response = delete_team(
            actor_user_id=self.actor_id,
            team_id=str(team_id),
        )
        result = data_of(response)
        self.assertTrue(result["deleted"])

        # It has been deleted by the Service, so exclude it from cleanup.
        self.team_ids.remove(team_id)

        self.assertIsNone(self._fetch_team(team_id))
        self.assertIsNone(self._fetch_membership(team_id, self.actor_id))


if __name__ == "__main__":
    unittest.main(verbosity=2)
