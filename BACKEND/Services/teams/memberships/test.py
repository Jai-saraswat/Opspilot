
"""PostgreSQL integration tests for team-membership Services.

Run from the project root:
    python -m BACKEND.Services.teams.memberships.test

These tests use real PostgreSQL records. Never run against production.
"""

from __future__ import annotations

import unittest
from uuid import UUID, uuid4

from psycopg.rows import dict_row

from BACKEND.Postgres.gateway import get_connection
from BACKEND.Services.teams.create_team import create_team
from BACKEND.Services.teams.memberships.add_team_member import add_team_member
from BACKEND.Services.teams.memberships.get_membership import get_membership
from BACKEND.Services.teams.memberships.list_team_members import list_team_members
from BACKEND.Services.teams.memberships.list_user_teams import list_user_teams
from BACKEND.Services.teams.memberships.update_membership_role import (
    update_membership_role,
)
from BACKEND.Services.teams.memberships.remove_team_member import (
    remove_team_member,
)


def data_of(response):
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


def rows_of(data):
    """Normalize common paginated response shape."""
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("items", "members", "teams", "results"):
            if isinstance(data.get(key), list):
                return data[key]
    raise AssertionError(f"Unrecognized list response shape: {data!r}")


class MembershipServicesIntegrationTests(unittest.TestCase):
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

        print(f"\nMembership Service tests using database: {cls.database_name}")

    def setUp(self):
        self.marker = uuid4().hex
        self.user_ids = []
        self.team_ids = []

        self.lead_id = self._create_user("lead")
        self.member_id = self._create_user("member")
        self.other_id = self._create_user("other")

        response = create_team(
            actor_user_id=self.lead_id,
            name=f"Membership Service {self.marker}",
            description="Membership integration test",
        )
        team = data_of(response)["team"]
        self.team_id = UUID(str(team["id"]))
        self.team_ids.append(self.team_id)

    def tearDown(self):
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
                        f"Membership test {label} {self.marker}",
                        f"membership-{label}-{self.marker}@example.invalid",
                        f"test-hash-{self.marker}",
                    ),
                )
                user_id = UUID(str(cur.fetchone()[0]))

        self.user_ids.append(user_id)
        return user_id

    def _fetch_membership(self, user_id):
        with get_connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    SELECT id, team_id, user_id, role, joined_at
                    FROM team_memberships
                    WHERE team_id = %s AND user_id = %s
                    """,
                    (self.team_id, UUID(str(user_id))),
                )
                return cur.fetchone()

    def _fetch_membership_count(self, user_id=None):
        with get_connection() as conn:
            with conn.cursor() as cur:
                if user_id is None:
                    cur.execute(
                        "SELECT COUNT(*) FROM team_memberships WHERE team_id = %s",
                        (self.team_id,),
                    )
                else:
                    cur.execute(
                        """
                        SELECT COUNT(*) FROM team_memberships
                        WHERE team_id = %s AND user_id = %s
                        """,
                        (self.team_id, UUID(str(user_id))),
                    )
                return cur.fetchone()[0]

    def _add_member(self, user_id, role="member"):
        response = add_team_member(
            actor_user_id=self.lead_id,
            team_id=str(self.team_id),
            user_id=str(user_id),
            role=role,
        )
        data_of(response)
        return response

    def test_add_member_persists_membership_and_role(self):
        self._add_member(self.member_id, "member")

        stored = self._fetch_membership(self.member_id)
        self.assertIsNotNone(stored)
        self.assertEqual(UUID(str(stored["team_id"])), self.team_id)
        self.assertEqual(UUID(str(stored["user_id"])), self.member_id)
        self.assertEqual(stored["role"], "member")
        self.assertEqual(self._fetch_membership_count(self.member_id), 1)

    def test_add_member_with_approver_role_persists_exact_role(self):
        self._add_member(self.member_id, "approver")

        stored = self._fetch_membership(self.member_id)
        self.assertIsNotNone(stored)
        self.assertEqual(stored["role"], "approver")

    def test_duplicate_membership_is_rejected_and_not_duplicated(self):
        self._add_member(self.member_id, "member")
        before = self._fetch_membership_count(self.member_id)

        response = add_team_member(
            actor_user_id=self.lead_id,
            team_id=str(self.team_id),
            user_id=str(self.member_id),
            role="approver",
        )

        assert_failure(self, response, 409)
        self.assertEqual(self._fetch_membership_count(self.member_id), before)

        # A failed duplicate attempt must not silently change the role.
        stored = self._fetch_membership(self.member_id)
        self.assertIsNotNone(stored)
        self.assertEqual(stored["role"], "member")

    def test_get_membership_matches_database(self):
        self._add_member(self.member_id, "approver")

        response = get_membership(
            actor_user_id=self.lead_id,
            team_id=str(self.team_id),
            user_id=str(self.member_id),
        )
        returned = data_of(response)

        stored = self._fetch_membership(self.member_id)
        self.assertIsNotNone(stored)

        # Support either a direct membership object or a named wrapper.
        if isinstance(returned, dict) and "membership" in returned:
            returned = returned["membership"]

        self.assertEqual(str(returned["team_id"]), str(stored["team_id"]))
        self.assertEqual(str(returned["user_id"]), str(stored["user_id"]))
        self.assertEqual(returned["role"], stored["role"])

    def test_list_team_members_matches_database_members(self):
        self._add_member(self.member_id, "member")
        self._add_member(self.other_id, "approver")

        response = list_team_members(
            actor_user_id=self.lead_id,
            team_id=str(self.team_id),
            limit=50,
            offset=0,
        )
        result = data_of(response)
        rows = rows_of(result)

        returned_ids = {str(row["user_id"]) for row in rows}
        self.assertIn(str(self.lead_id), returned_ids)
        self.assertIn(str(self.member_id), returned_ids)
        self.assertIn(str(self.other_id), returned_ids)

        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT user_id FROM team_memberships WHERE team_id = %s",
                    (self.team_id,),
                )
                db_ids = {str(row[0]) for row in cur.fetchall()}

        self.assertEqual(returned_ids, db_ids)

        # Verify the roles in PostgreSQL, independently of the Service output.
        self.assertEqual(self._fetch_membership(self.member_id)["role"], "member")
        self.assertEqual(self._fetch_membership(self.other_id)["role"], "approver")

    def test_list_team_members_search_and_pagination(self):
        searchable_id = self._create_user("search-target")
        other_searchable_id = self._create_user("search-target-two")

        self._add_member(searchable_id, "member")
        self._add_member(other_searchable_id, "approver")

        # Both fixture users contain this searchable substring.
        search_term = "search-target"

        page_one = data_of(
            list_team_members(
                actor_user_id=self.lead_id,
                team_id=str(self.team_id),
                search=search_term,
                limit=1,
                offset=0,
            )
        )
        page_two = data_of(
            list_team_members(
                actor_user_id=self.lead_id,
                team_id=str(self.team_id),
                search=search_term,
                limit=1,
                offset=1,
            )
        )

        first_rows = rows_of(page_one)
        second_rows = rows_of(page_two)

        self.assertEqual(len(first_rows), 1)
        self.assertEqual(len(second_rows), 1)

        first_id = str(first_rows[0]["user_id"])
        second_id = str(second_rows[0]["user_id"])

        self.assertNotEqual(first_id, second_id)
        self.assertEqual(
            {first_id, second_id},
            {str(searchable_id), str(other_searchable_id)},
        )

        # Verify that the two matching records really exist in PostgreSQL.
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT COUNT(*)
                    FROM team_memberships tm
                             JOIN users u ON u.id = tm.user_id
                    WHERE tm.team_id = %s
                      AND (
                        u.full_name ILIKE %s
                            OR u.email ILIKE %s
                        )
                    """,
                    (self.team_id, f"%{search_term}%", f"%{search_term}%"),
                )
                db_count = cur.fetchone()[0]

        self.assertEqual(db_count, 2)

    def test_list_user_teams_contains_membership_team(self):
        self._add_member(self.member_id, "approver")

        response = list_user_teams(
            actor_user_id=self.member_id,
            user_id=str(self.member_id),
            limit=50,
            offset=0,
        )
        rows = rows_of(data_of(response))

        returned_team_ids = {str(row["id"]) for row in rows}
        self.assertIn(str(self.team_id), returned_team_ids)

        # Independently validate membership and role in PostgreSQL.
        stored = self._fetch_membership(self.member_id)
        self.assertIsNotNone(stored)
        self.assertEqual(str(stored["team_id"]), str(self.team_id))
        self.assertEqual(str(stored["user_id"]), str(self.member_id))
        self.assertEqual(stored["role"], "approver")

        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id
                    FROM teams
                    WHERE id = %s
                      AND id IN (SELECT team_id
                                 FROM team_memberships
                                 WHERE user_id = %s)
                    """,
                    (self.team_id, self.member_id),
                )
                self.assertIsNotNone(cur.fetchone())

    def test_update_membership_role_persists_role_change(self):
        self._add_member(self.member_id, "member")

        response = update_membership_role(
            actor_user_id=self.lead_id,
            team_id=str(self.team_id),
            user_id=str(self.member_id),
            role="approver",
        )
        data_of(response)

        stored = self._fetch_membership(self.member_id)
        self.assertIsNotNone(stored)
        self.assertEqual(stored["role"], "approver")

    def test_invalid_role_does_not_change_persisted_role(self):
        self._add_member(self.member_id, "member")

        response = update_membership_role(
            actor_user_id=self.lead_id,
            team_id=str(self.team_id),
            user_id=str(self.member_id),
            role="administrator",
        )
        assert_failure(self, response)

        stored = self._fetch_membership(self.member_id)
        self.assertIsNotNone(stored)
        self.assertEqual(stored["role"], "member")

    def test_remove_member_deletes_database_relationship(self):
        self._add_member(self.member_id, "member")
        self.assertIsNotNone(self._fetch_membership(self.member_id))

        response = remove_team_member(
            actor_user_id=self.lead_id,
            team_id=str(self.team_id),
            user_id=str(self.member_id),
        )
        data_of(response)

        self.assertIsNone(self._fetch_membership(self.member_id))
        self.assertEqual(self._fetch_membership_count(self.member_id), 0)

    def test_remove_member_does_not_remove_other_memberships(self):
        # Give the same user memberships in two distinct teams.
        self._add_member(self.member_id, "member")

        second_response = create_team(
            actor_user_id=self.lead_id,
            name=f"Membership Service second {self.marker}",
            description="Second test team",
        )
        second_team = data_of(second_response)["team"]
        second_team_id = UUID(str(second_team["id"]))
        self.team_ids.append(second_team_id)

        add_response = add_team_member(
            actor_user_id=self.lead_id,
            team_id=str(second_team_id),
            user_id=str(self.member_id),
            role="approver",
        )
        data_of(add_response)

        removal = remove_team_member(
            actor_user_id=self.lead_id,
            team_id=str(self.team_id),
            user_id=str(self.member_id),
        )
        data_of(removal)

        with get_connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    SELECT role FROM team_memberships
                    WHERE team_id = %s AND user_id = %s
                    """,
                    (self.team_id, self.member_id),
                )
                self.assertIsNone(cur.fetchone())

                cur.execute(
                    """
                    SELECT role FROM team_memberships
                    WHERE team_id = %s AND user_id = %s
                    """,
                    (second_team_id, self.member_id),
                )
                remaining = cur.fetchone()

        self.assertIsNotNone(remaining)
        self.assertEqual(remaining["role"], "approver")


if __name__ == "__main__":
    unittest.main(verbosity=2)
