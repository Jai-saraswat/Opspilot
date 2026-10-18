"""PostgreSQL integration tests for activity Operations.

Run from the project root:
    python -m BACKEND.Postgres.Operations.activity.test

These tests use real PostgreSQL records, not mocks.
Run only against a disposable development/test database.
"""

from __future__ import annotations

import unittest
from typing import Any
from uuid import UUID, uuid4

from psycopg.rows import dict_row

from BACKEND.Postgres.gateway import get_connection
from BACKEND.Postgres.Operations.activity import errors as activity_errors
from BACKEND.Postgres.Operations.activity.create_activity import (
    create_activity,
)
from BACKEND.Postgres.Operations.activity.get_activity_by_id import (
    get_activity_by_id,
)
from BACKEND.Postgres.Operations.activity.get_user_activity import (
    get_user_activity,
)
from BACKEND.Postgres.Operations.activity.list_team_activity import (
    list_team_activity,
)
from BACKEND.Postgres.Operations.activity.list_user_activity import (
    list_user_activity,
)
from BACKEND.Postgres.Operations.activity.list_work_item_activity import (
    list_work_item_activity,
)


class RollbackProbe(Exception):
    """Force a caller-owned PostgreSQL transaction to roll back."""


class ActivityOperationsIntegrationTests(unittest.TestCase):
    """Validate activity Operations against the actual database."""

    @classmethod
    def setUpClass(cls) -> None:
        with get_connection() as connection:
            with connection.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    "SELECT current_database() AS database_name"
                )
                row = cursor.fetchone()

                if row is None:
                    raise RuntimeError(
                        "Could not determine the connected database."
                    )

                cls.database_name = row["database_name"]

                if any(
                    marker in cls.database_name.lower()
                    for marker in ("prod", "production", "live")
                ):
                    raise RuntimeError(
                        "Refusing to run integration tests against "
                        f"production-looking database {cls.database_name!r}."
                    )

                required_tables = (
                    "users",
                    "teams",
                    "team_memberships",
                    "work_items",
                    "work_item_activity",
                )

                for table_name in required_tables:
                    cursor.execute(
                        "SELECT to_regclass(%s) AS table_name",
                        (f"public.{table_name}",),
                    )
                    result = cursor.fetchone()

                    if result is None or result["table_name"] is None:
                        raise RuntimeError(
                            f"Required table public.{table_name} is missing."
                        )

        print(
            "\nActivity Operations tests connected to PostgreSQL: "
            f"{cls.database_name}"
        )

    def setUp(self) -> None:
        self.marker = uuid4().hex
        self.created_user_ids: list[UUID] = []
        self.created_team_ids: list[UUID] = []
        self.created_work_item_ids: list[UUID] = []

        self.actor_id = self._create_user("actor")
        self.other_user_id = self._create_user("other")
        self.outsider_id = self._create_user("outsider")

        self.team_id = self._create_team(
            name=f"Activity Test Team {self.marker}",
            created_by=self.actor_id,
        )

        self._add_member(self.team_id, self.actor_id, "lead")
        self._add_member(self.team_id, self.other_user_id, "member")

        self.work_item_id = self._create_work_item(self.team_id)

    def tearDown(self) -> None:
        """Remove only test-owned records in foreign-key-safe order."""
        with get_connection() as connection:
            with connection.cursor() as cursor:
                for work_item_id in self.created_work_item_ids:
                    cursor.execute(
                        """
                        DELETE FROM work_item_activity
                        WHERE work_item_id = %s
                        """,
                        (work_item_id,),
                    )
                    cursor.execute(
                        """
                        DELETE FROM work_item_approval_requests
                        WHERE work_item_id = %s
                        """,
                        (work_item_id,),
                    )
                    cursor.execute(
                        "DELETE FROM work_items WHERE id = %s",
                        (work_item_id,),
                    )

                # Membership rows cascade from their team.
                for team_id in self.created_team_ids:
                    cursor.execute(
                        "DELETE FROM teams WHERE id = %s",
                        (team_id,),
                    )

                # Teams reference their creator, so delete teams first.
                for user_id in self.created_user_ids:
                    cursor.execute(
                        "DELETE FROM users WHERE id = %s",
                        (user_id,),
                    )

    # ---------------------------------------------------------------
    # Fixture helpers: use the supplied schema's actual column names
    # ---------------------------------------------------------------

    def _create_user(self, label: str) -> UUID:
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
                    RETURNING id
                    """,
                    (
                        f"Activity Test {label} {self.marker}",
                        f"activity-test-{self.marker}-{label}@example.invalid",
                        f"test-placeholder-{uuid4().hex}",
                    ),
                )
                user_id = UUID(str(cursor.fetchone()[0]))

        self.created_user_ids.append(user_id)
        return user_id

    def _create_team(
        self,
        *,
        name: str,
        created_by: UUID,
    ) -> UUID:
        with get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO teams (name, description, created_by)
                    VALUES (%s, %s, %s)
                    RETURNING id
                    """,
                    (
                        name,
                        "Temporary activity Operations test team.",
                        created_by,
                    ),
                )
                team_id = UUID(str(cursor.fetchone()[0]))

        self.created_team_ids.append(team_id)
        return team_id

    @staticmethod
    def _add_member(
        team_id: UUID,
        user_id: UUID,
        role: str,
    ) -> None:
        with get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO team_memberships (team_id, user_id, role)
                    VALUES (%s, %s, %s)
                    """,
                    (team_id, user_id, role),
                )

    def _create_work_item(self, team_id: UUID) -> UUID:
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
                    RETURNING id
                    """,
                    (
                        f"Activity Work Item {self.marker}",
                        "Temporary record for activity Operations testing.",
                        "action",
                        team_id,
                        self.actor_id,
                    ),
                )
                item_id = UUID(str(cursor.fetchone()[0]))

        self.created_work_item_ids.append(item_id)
        return item_id

    def _create_event(
        self,
        *,
        work_item_id: UUID | None = None,
        action: str = "status_changed",
        actor_id: UUID | None = None,
    ) -> dict[str, Any]:
        return create_activity(
            work_item_id=work_item_id or self.work_item_id,
            action=action,
            actor_id=self.actor_id if actor_id is None else actor_id,
            details={
                "test_marker": self.marker,
                "origin": "activity_operations_test",
            },
        )

    def _fetch_activity_count(
        self,
        *,
        work_item_id: UUID | None = None,
        actor_id: UUID | None = None,
    ) -> int:
        conditions: list[str] = []
        parameters: list[Any] = []

        if work_item_id is not None:
            conditions.append("work_item_id = %s")
            parameters.append(work_item_id)

        if actor_id is not None:
            conditions.append("actor_id = %s")
            parameters.append(actor_id)

        where_clause = (
            "WHERE " + " AND ".join(conditions)
            if conditions
            else ""
        )

        with get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT COUNT(*)
                    FROM work_item_activity
                    {where_clause}
                    """,
                    tuple(parameters),
                )
                return cursor.fetchone()[0]

    # ---------------------------------------------------------------
    # Activity Operations tests
    # ---------------------------------------------------------------

    def test_create_activity_persists_json_and_foreign_keys(self):
        event = self._create_event(action="created")

        stored = get_activity_by_id(event["id"])

        self.assertIsNotNone(stored)
        self.assertEqual(stored["id"], event["id"])
        self.assertEqual(stored["work_item_id"], self.work_item_id)
        self.assertEqual(stored["actor_id"], self.actor_id)
        self.assertEqual(stored["action"], "created")
        self.assertEqual(
            stored["details"]["test_marker"],
            self.marker,
        )
        self.assertIsNotNone(stored["created_at"])

    def test_get_activity_returns_none_for_missing_id(self):
        self.assertIsNone(get_activity_by_id(uuid4()))

    def test_list_work_item_activity_filters_and_paginates(self):
        self._create_event(action="priority_changed")
        self._create_event(action="priority_changed")
        self._create_event(action="status_changed")

        page_one = list_work_item_activity(
            self.work_item_id,
            action="priority_changed",
            limit=1,
            offset=0,
        )
        page_two = list_work_item_activity(
            self.work_item_id,
            action="priority_changed",
            limit=1,
            offset=1,
        )

        self.assertEqual(page_one["total"], 2)
        self.assertEqual(page_two["total"], 2)
        self.assertEqual(len(page_one["items"]), 1)
        self.assertEqual(len(page_two["items"]), 1)
        self.assertNotEqual(
            page_one["items"][0]["id"],
            page_two["items"][0]["id"],
        )

    def test_list_user_activity_applies_action_and_team_scope(self):
        event = self._create_event(action="user_feed_test")

        visible = list_user_activity(
            self.actor_id,
            action="user_feed_test",
            visible_team_ids=[self.team_id],
            limit=100,
            offset=0,
        )

        self.assertEqual(visible["total"], 1)
        self.assertEqual(visible["items"][0]["id"], event["id"])

        hidden = list_user_activity(
            self.actor_id,
            action="user_feed_test",
            visible_team_ids=[],
            limit=100,
            offset=0,
        )

        self.assertEqual(hidden["total"], 0)
        self.assertEqual(hidden["items"], [])

    def test_get_user_activity_wrapper_matches_canonical_operation(self):
        self._create_event(action="user_wrapper_test")

        canonical = list_user_activity(
            self.actor_id,
            action="user_wrapper_test",
            visible_team_ids=[self.team_id],
        )
        wrapper = get_user_activity(
            self.actor_id,
            action="user_wrapper_test",
            visible_team_ids=[self.team_id],
        )

        self.assertEqual(wrapper["total"], canonical["total"])
        self.assertEqual(
            [row["id"] for row in wrapper["items"]],
            [row["id"] for row in canonical["items"]],
        )

    def test_list_team_activity_returns_only_requested_team(self):
        event = self._create_event(action="team_feed_test")

        # Create an item in another team and add an event to it.
        other_team_id = self._create_team(
            name=f"Activity Other Team {self.marker}",
            created_by=self.actor_id,
        )
        other_item_id = self._create_work_item(other_team_id)
        self._create_event(
            work_item_id=other_item_id,
            action="team_feed_test",
        )

        result = list_team_activity(
            self.team_id,
            action="team_feed_test",
            limit=100,
            offset=0,
        )

        self.assertEqual(result["total"], 1)
        self.assertEqual(result["items"][0]["id"], event["id"])
        self.assertEqual(
            result["items"][0]["work_item_id"],
            self.work_item_id,
        )

    def test_caller_owned_transaction_rolls_back_activity_insert(self):
        before_count = self._fetch_activity_count(
            work_item_id=self.work_item_id,
        )

        try:
            with get_connection() as connection:
                create_activity(
                    work_item_id=self.work_item_id,
                    actor_id=self.actor_id,
                    action="transaction_rollback_test",
                    details={"marker": self.marker},
                    connection=connection,
                )

                # Force rollback after the activity insert.
                raise RollbackProbe()

        except RollbackProbe:
            pass

        after_count = self._fetch_activity_count(
            work_item_id=self.work_item_id,
        )

        self.assertEqual(
            after_count,
            before_count,
            "The activity insert must roll back with the caller transaction.",
        )

    def test_invalid_pagination_is_rejected(self):
        with self.assertRaises(ValueError):
            list_work_item_activity(
                self.work_item_id,
                limit=0,
            )

        with self.assertRaises(ValueError):
            list_user_activity(
                self.actor_id,
                offset=-1,
            )

        with self.assertRaises(ValueError):
            list_team_activity(
                self.team_id,
                limit=101,
            )

    def test_activity_error_types_are_available(self):
        self.assertTrue(
            issubclass(
                activity_errors.InvalidActivityRecordError,
                Exception,
            )
        )
        self.assertTrue(
            issubclass(
                activity_errors.ActivityRelatedRecordNotFoundError,
                Exception,
            )
        )
        self.assertTrue(
            issubclass(
                activity_errors.ActivityDatabaseError,
                Exception,
            )
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)