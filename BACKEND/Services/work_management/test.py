"""PostgreSQL integration tests for work-management Services.

Run from the project root:
    python -m BACKEND.Services.work_management.test

Uses real PostgreSQL records. Run only against a disposable
development/test database.
"""

from __future__ import annotations

import unittest
from unittest.mock import patch
from uuid import UUID, uuid4

from psycopg.rows import dict_row

from BACKEND.Postgres.gateway import get_connection
from BACKEND.Postgres.Operations.activity.errors import ActivityDatabaseError
from BACKEND.Postgres.Operations.work_items.get_work_item_by_id import (
    get_work_item_by_id as get_work_item_operation,
)
from BACKEND.Services.work_management.assign_work_item import assign_work_item
from BACKEND.Services.work_management.change_work_item_priority import (
    change_work_item_priority,
)
from BACKEND.Services.work_management.change_work_item_status import (
    change_work_item_status,
)
from BACKEND.Services.work_management.claim_work_item import claim_work_item
from BACKEND.Services.work_management.create_work_item import create_work_item
from BACKEND.Services.work_management.get_team_work_items import (
    get_team_work_items,
)
from BACKEND.Services.work_management.get_user_work_items import (
    get_user_work_items,
)
from BACKEND.Services.work_management.get_work_item import get_work_item
from BACKEND.Services.work_management.list_work_items import list_work_items
from BACKEND.Services.work_management.update_work_item import update_work_item


def response_data(response):
    """Extract successful ServiceResponse data or show the actual failure."""
    if not getattr(response, "success", False):
        raise AssertionError(
            "Expected successful ServiceResponse; "
            f"HTTP={getattr(response, 'http_status', None)}, "
            f"error={getattr(response, 'error', None)!r}"
        )

    return response.outputs.data


class WorkItemTestFixture:
    """Shared real-PostgreSQL fixture for work-management tests."""

    @classmethod
    def setUpClass(cls):
        with get_connection() as connection:
            with connection.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    "SELECT current_database() AS database_name"
                )
                row = cursor.fetchone()

                if row is None:
                    raise RuntimeError(
                        "Could not identify the connected PostgreSQL database."
                    )

                cls.database_name = row["database_name"]
                lowered = cls.database_name.lower()

                if any(
                    marker in lowered
                    for marker in ("prod", "production", "live")
                ):
                    raise RuntimeError(
                        "Refusing to run destructive integration tests "
                        f"against production-looking database {cls.database_name!r}."
                    )

                required_tables = (
                    "users",
                    "teams",
                    "team_memberships",
                    "work_items",
                    "work_item_activity",
                    "work_item_approval_requests",
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
            "\nWork-management tests connected to PostgreSQL: "
            f"{cls.database_name}"
        )

    def setUp(self):
        self.marker = uuid4().hex
        self.created_user_ids: list[UUID] = []
        self.created_team_ids: list[UUID] = []
        self.created_work_item_ids: list[UUID] = []

        self.actor_id = self._create_user("lead")
        self.member_id = self._create_user("member")
        self.outsider_id = self._create_user("outsider")

        self.team_id = self._create_team()

        self._add_member(self.actor_id, "lead")
        self._add_member(self.member_id, "member")

    def tearDown(self):
        """Delete test-owned rows in foreign-key-safe order."""
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

                # Memberships are configured to cascade from teams.
                for team_id in self.created_team_ids:
                    cursor.execute(
                        "DELETE FROM teams WHERE id = %s",
                        (team_id,),
                    )

                # Teams reference their creator, so teams go first.
                for user_id in self.created_user_ids:
                    cursor.execute(
                        "DELETE FROM users WHERE id = %s",
                        (user_id,),
                    )

    # ---------------------------------------------------------------
    # Fixture builders: use the current schema's actual column names
    # ---------------------------------------------------------------

    def _create_user(self, label: str) -> UUID:
        email = f"wm-test-{self.marker}-{label}@example.invalid"

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
                        f"Work Management Test {label} {self.marker}",
                        email,
                        f"test-placeholder-{uuid4().hex}",
                    ),
                )
                user_id = UUID(str(cursor.fetchone()[0]))

        self.created_user_ids.append(user_id)
        return user_id

    def _create_team(self) -> UUID:
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
                    RETURNING id
                    """,
                    (
                        f"WM Test Team {self.marker}",
                        "Temporary work-management integration-test team.",
                        self.actor_id,
                    ),
                )
                team_id = UUID(str(cursor.fetchone()[0]))

        self.created_team_ids.append(team_id)
        return team_id

    def _add_member(self, user_id: UUID, role: str) -> None:
        if role not in {"lead", "member", "approver"}:
            raise ValueError(f"Invalid test membership role: {role}")

        with get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO team_memberships (
                        team_id,
                        user_id,
                        role
                    )
                    VALUES (%s, %s, %s)
                    """,
                    (self.team_id, user_id, role),
                )

    def _create_item(self, label: str = "Item") -> dict:
        response = create_work_item(
            actor_user_id=self.actor_id,
            title=f"{label} {self.marker}",
            description=f"PostgreSQL test description {self.marker}",
            type="action",
            team_id=self.team_id,
            priority="medium",
        )

        item = response_data(response)["work_item"]
        self.created_work_item_ids.append(UUID(item["id"]))
        return item

    def _fetch_item_row(self, work_item_id: UUID) -> dict | None:
        """Read the stored record directly, independently of the Service."""
        with get_connection() as connection:
            with connection.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    """
                    SELECT
                        id,
                        title,
                        description,
                        type,
                        status,
                        priority,
                        team_id,
                        created_by,
                        assignee_id,
                        created_at,
                        updated_at,
                        completed_at
                    FROM work_items
                    WHERE id = %s
                    """,
                    (work_item_id,),
                )
                row = cursor.fetchone()

        return dict(row) if row is not None else None

    def _activity_rows(
        self,
        work_item_id: UUID,
        action: str | None = None,
    ) -> list[dict]:
        """Read persisted activity entries for a work item."""
        query = """
            SELECT
                id,
                work_item_id,
                actor_id,
                action,
                details,
                created_at
            FROM work_item_activity
            WHERE work_item_id = %s
        """
        parameters: list = [work_item_id]

        if action is not None:
            query += " AND action = %s"
            parameters.append(action)

        query += " ORDER BY created_at DESC, id DESC"

        with get_connection() as connection:
            with connection.cursor(row_factory=dict_row) as cursor:
                cursor.execute(query, tuple(parameters))
                return [dict(row) for row in cursor.fetchall()]


class WorkItemServicesIntegrationTests(
    WorkItemTestFixture,
    unittest.TestCase,
):
    """Validate work-item Services, activity integration, and DB state."""

    def test_create_persists_item_and_creation_activity(self):
        item = self._create_item()
        stored = self._fetch_item_row(UUID(item["id"]))

        self.assertIsNotNone(stored)
        self.assertEqual(stored["title"], item["title"])
        self.assertEqual(stored["team_id"], self.team_id)
        self.assertEqual(stored["created_by"], self.actor_id)
        self.assertEqual(stored["status"], "open")
        self.assertEqual(stored["priority"], "medium")

        events = self._activity_rows(
            UUID(item["id"]),
            "work_item_created",
        )
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["actor_id"], self.actor_id)
        self.assertEqual(events[0]["details"]["priority"], "medium")

    def test_activity_failure_rolls_back_work_item_creation(self):
        # This replaces the service helper only; the surrounding transaction
        # and the PostgreSQL work-item Operation still run for real.
        with patch(
            "BACKEND.Services.work_management.create_work_item."
            "record_work_item_activity",
            side_effect=ActivityDatabaseError("simulated activity failure"),
        ):
            response = create_work_item(
                actor_user_id=self.actor_id,
                title=f"Rollback {self.marker}",
                description="This creation should not be committed.",
                type="action",
                team_id=self.team_id,
                priority="medium",
            )

        self.assertFalse(response.success)
        self.assertEqual(response.http_status, 500)

        with get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT COUNT(*)
                    FROM work_items
                    WHERE team_id = %s AND title = %s
                    """,
                    (self.team_id, f"Rollback {self.marker}"),
                )
                self.assertEqual(cursor.fetchone()[0], 0)

    def test_get_work_item_enforces_team_access(self):
        item = self._create_item()

        allowed = get_work_item(
            actor_user_id=self.actor_id,
            work_item_id=item["id"],
        )
        self.assertEqual(
            response_data(allowed)["work_item"]["id"],
            item["id"],
        )

        denied = get_work_item(
            actor_user_id=self.outsider_id,
            work_item_id=item["id"],
        )
        self.assertFalse(denied.success)
        self.assertEqual(denied.http_status, 403)

    def test_update_persists_and_records_old_and_new_values(self):
        item = self._create_item()
        new_title = f"Updated {self.marker}"

        response = update_work_item(
            actor_user_id=self.actor_id,
            work_item_id=item["id"],
            expected_updated_at=self._fetch_item_row(
                UUID(item["id"])
            )["updated_at"],
            title=new_title,
        )
        response_data(response)

        stored = self._fetch_item_row(UUID(item["id"]))
        self.assertEqual(stored["title"], new_title)

        events = self._activity_rows(
            UUID(item["id"]),
            "work_item_updated",
        )
        self.assertEqual(len(events), 1)
        self.assertEqual(
            events[0]["details"]["title"]["old"],
            item["title"],
        )
        self.assertEqual(
            events[0]["details"]["title"]["new"],
            new_title,
        )

    def test_stale_update_is_rejected_without_extra_activity(self):
        item = self._create_item()
        before = self._fetch_item_row(UUID(item["id"]))
        original_timestamp = before["updated_at"]

        first = update_work_item(
            actor_user_id=self.actor_id,
            work_item_id=item["id"],
            expected_updated_at=original_timestamp,
            title=f"First update {self.marker}",
        )
        response_data(first)

        event_count = len(
            self._activity_rows(
                UUID(item["id"]),
                "work_item_updated",
            )
        )

        stale = update_work_item(
            actor_user_id=self.actor_id,
            work_item_id=item["id"],
            expected_updated_at=original_timestamp,
            title=f"Stale update {self.marker}",
        )

        self.assertFalse(stale.success)
        self.assertEqual(stale.http_status, 409)
        self.assertEqual(
            len(
                self._activity_rows(
                    UUID(item["id"]),
                    "work_item_updated",
                )
            ),
            event_count,
        )

        stored = self._fetch_item_row(UUID(item["id"]))
        self.assertEqual(stored["title"], f"First update {self.marker}")

    def test_no_op_update_rejects_stale_timestamp(self):
        item = self._create_item()
        initial = self._fetch_item_row(UUID(item["id"]))

        # First change the title, making the original timestamp stale.
        changed = update_work_item(
            actor_user_id=self.actor_id,
            work_item_id=item["id"],
            expected_updated_at=initial["updated_at"],
            title=f"Current title {self.marker}",
        )
        response_data(changed)

        after_change = self._fetch_item_row(UUID(item["id"]))
        activity_count = len(
            self._activity_rows(
                UUID(item["id"]),
                "work_item_updated",
            )
        )

        # Supplying the current title with the old timestamp is still stale.
        response = update_work_item(
            actor_user_id=self.actor_id,
            work_item_id=item["id"],
            expected_updated_at=initial["updated_at"],
            title=after_change["title"],
        )

        self.assertFalse(response.success)
        self.assertEqual(response.http_status, 409)
        self.assertEqual(
            len(
                self._activity_rows(
                    UUID(item["id"]),
                    "work_item_updated",
                )
            ),
            activity_count,
        )

    def test_assignment_persists_and_records_assignee_change(self):
        item = self._create_item()
        before = self._fetch_item_row(UUID(item["id"]))

        response = assign_work_item(
            actor_user_id=self.actor_id,
            work_item_id=item["id"],
            assignee_id=self.member_id,
            expected_updated_at=before["updated_at"],
        )
        response_data(response)

        stored = self._fetch_item_row(UUID(item["id"]))
        self.assertEqual(stored["assignee_id"], self.member_id)

        events = self._activity_rows(
            UUID(item["id"]),
            "assignee_changed",
        )
        self.assertEqual(len(events), 1)
        self.assertIsNone(events[0]["details"]["old_assignee_id"])
        self.assertEqual(
            events[0]["details"]["new_assignee_id"],
            str(self.member_id),
        )

    def test_no_op_assignment_rejects_stale_timestamp(self):
        item = self._create_item()
        before = self._fetch_item_row(UUID(item["id"]))

        assigned = assign_work_item(
            actor_user_id=self.actor_id,
            work_item_id=item["id"],
            assignee_id=self.member_id,
            expected_updated_at=before["updated_at"],
        )
        response_data(assigned)

        after = self._fetch_item_row(UUID(item["id"]))
        existing_event_count = len(
            self._activity_rows(
                UUID(item["id"]),
                "assignee_changed",
            )
        )

        # Same assignee, but a timestamp from before assignment.
        stale_no_op = assign_work_item(
            actor_user_id=self.actor_id,
            work_item_id=item["id"],
            assignee_id=self.member_id,
            expected_updated_at=before["updated_at"],
        )

        self.assertFalse(stale_no_op.success)
        self.assertEqual(stale_no_op.http_status, 409)
        self.assertEqual(
            len(
                self._activity_rows(
                    UUID(item["id"]),
                    "assignee_changed",
                )
            ),
            existing_event_count,
        )

        stored = self._fetch_item_row(UUID(item["id"]))
        self.assertEqual(stored["assignee_id"], self.member_id)
        self.assertEqual(stored["updated_at"], after["updated_at"])

    def test_claim_persists_assignee_and_claim_activity(self):
        item = self._create_item()
        before = self._fetch_item_row(UUID(item["id"]))

        response = claim_work_item(
            actor_user_id=self.member_id,
            work_item_id=item["id"],
            expected_updated_at=before["updated_at"],
        )
        response_data(response)

        stored = self._fetch_item_row(UUID(item["id"]))
        self.assertEqual(stored["assignee_id"], self.member_id)

        events = self._activity_rows(
            UUID(item["id"]),
            "work_item_claimed",
        )
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["actor_id"], self.member_id)

    def test_priority_change_persists_and_records_event(self):
        item = self._create_item()
        before = self._fetch_item_row(UUID(item["id"]))

        response = change_work_item_priority(
            actor_user_id=self.actor_id,
            work_item_id=item["id"],
            priority="critical",
            expected_updated_at=before["updated_at"],
        )
        response_data(response)

        stored = self._fetch_item_row(UUID(item["id"]))
        self.assertEqual(stored["priority"], "critical")

        events = self._activity_rows(
            UUID(item["id"]),
            "priority_changed",
        )
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["details"]["old_priority"], "medium")
        self.assertEqual(events[0]["details"]["new_priority"], "critical")

    def test_status_changes_and_cancellation_are_recorded(self):
        item = self._create_item()
        before = self._fetch_item_row(UUID(item["id"]))

        started = change_work_item_status(
            actor_user_id=self.actor_id,
            work_item_id=item["id"],
            status="in_progress",
            expected_updated_at=before["updated_at"],
        )
        response_data(started)

        in_progress = self._fetch_item_row(UUID(item["id"]))

        cancelled = change_work_item_status(
            actor_user_id=self.actor_id,
            work_item_id=item["id"],
            status="cancelled",
            expected_updated_at=in_progress["updated_at"],
        )
        response_data(cancelled)

        stored = self._fetch_item_row(UUID(item["id"]))
        self.assertEqual(stored["status"], "cancelled")
        self.assertIsNone(stored["completed_at"])

        events = self._activity_rows(
            UUID(item["id"]),
            "status_changed",
        )
        self.assertEqual(len(events), 2)

        transitions = {
            (
                event["details"]["old_status"],
                event["details"]["new_status"],
            )
            for event in events
        }
        self.assertEqual(
            transitions,
            {
                ("open", "in_progress"),
                ("in_progress", "cancelled"),
            },
        )

    def test_invalid_status_transition_changes_neither_state_nor_activity(self):
        item = self._create_item()
        before = self._fetch_item_row(UUID(item["id"]))
        original_event_count = len(
            self._activity_rows(UUID(item["id"]), "status_changed")
        )

        response = change_work_item_status(
            actor_user_id=self.actor_id,
            work_item_id=item["id"],
            status="resolved",
            expected_updated_at=before["updated_at"],
        )

        self.assertFalse(response.success)
        self.assertEqual(response.http_status, 409)

        stored = self._fetch_item_row(UUID(item["id"]))
        self.assertEqual(stored["status"], "open")
        self.assertIsNone(stored["completed_at"])
        self.assertEqual(
            len(
                self._activity_rows(
                    UUID(item["id"]),
                    "status_changed",
                )
            ),
            original_event_count,
        )

    def test_successful_resolution_sets_completed_at_and_activity(self):
        item = self._create_item("Resolution Test")
        work_item_id = UUID(item["id"])

        before = self._fetch_item_row(work_item_id)

        started = change_work_item_status(
            actor_user_id=self.actor_id,
            work_item_id=item["id"],
            status="in_progress",
            expected_updated_at=before["updated_at"],
        )
        response_data(started)

        in_progress = self._fetch_item_row(work_item_id)

        self.assertEqual(in_progress["status"], "in_progress")
        self.assertIsNone(in_progress["completed_at"])

        resolved_response = change_work_item_status(
            actor_user_id=self.actor_id,
            work_item_id=item["id"],
            status="resolved",
            expected_updated_at=in_progress["updated_at"],
        )
        response_data(resolved_response)

        # Confirm the actual PostgreSQL row satisfies the schema invariant.
        resolved = self._fetch_item_row(work_item_id)
        self.assertEqual(resolved["status"], "resolved")
        self.assertIsNotNone(resolved["completed_at"])

        events = self._activity_rows(work_item_id, "status_changed")
        transitions = {
            (
                event["details"]["old_status"],
                event["details"]["new_status"],
            )
            for event in events
        }

        self.assertIn(("open", "in_progress"), transitions)
        self.assertIn(("in_progress", "resolved"), transitions)

    def test_list_work_items_filters_and_paginates_in_postgresql(self):
        first = self._create_item("List First")
        second = self._create_item("List Second")

        response = list_work_items(
            actor_user_id=self.actor_id,
            team_id=self.team_id,
            limit=1,
            offset=0,
            search=self.marker,
        )
        data = response_data(response)

        self.assertEqual(data["limit"], 1)
        self.assertEqual(data["offset"], 0)
        self.assertEqual(len(data["items"]), 1)
        self.assertGreaterEqual(data["total"], 2)
        self.assertIn(
            data["items"][0]["id"],
            {first["id"], second["id"]},
        )

        # Independently verify the filtered total with a database query.
        with get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT COUNT(*)
                    FROM work_items
                    WHERE team_id = %s
                      AND (title ILIKE %s OR description ILIKE %s)
                    """,
                    (
                        self.team_id,
                        f"%{self.marker}%",
                        f"%{self.marker}%",
                    ),
                )
                expected_total = cursor.fetchone()[0]

        self.assertEqual(data["total"], expected_total)

    def test_team_work_item_service_lists_items_for_team(self):
        item = self._create_item("Team Listing")

        response = get_team_work_items(
            actor_user_id=self.actor_id,
            team_id=self.team_id,
            search=self.marker,
            limit=100,
        )
        data = response_data(response)

        self.assertIn(
            item["id"],
            {row["id"] for row in data["items"]},
        )

    def test_user_work_item_service_lists_current_assignment(self):
        item = self._create_item("User Listing")
        before = self._fetch_item_row(UUID(item["id"]))

        assigned = assign_work_item(
            actor_user_id=self.actor_id,
            work_item_id=item["id"],
            assignee_id=self.member_id,
            expected_updated_at=before["updated_at"],
        )
        response_data(assigned)

        response = get_user_work_items(
            actor_user_id=self.member_id,
            limit=100,
            offset=0,
        )
        data = response_data(response)

        self.assertIn(
            item["id"],
            {row["id"] for row in data["items"]},
        )

    def test_activity_failure_rolls_back_priority_change(self):
        item = self._create_item("Priority Rollback")
        work_item_id = UUID(item["id"])

        before = self._fetch_item_row(work_item_id)
        old_activity_count = len(
            self._activity_rows(work_item_id, "priority_changed")
        )

        with patch(
            "BACKEND.Services.work_management.change_work_item_priority."
            "record_work_item_activity",
            side_effect=ActivityDatabaseError(
                "simulated activity failure"
            ),
        ):
            response = change_work_item_priority(
                actor_user_id=self.actor_id,
                work_item_id=item["id"],
                priority="high",
                expected_updated_at=before["updated_at"],
            )

        self.assertFalse(response.success)
        self.assertEqual(response.http_status, 500)

        # The attempted priority update must have rolled back.
        after = self._fetch_item_row(work_item_id)
        self.assertEqual(after["priority"], "medium")

        self.assertEqual(
            len(self._activity_rows(work_item_id, "priority_changed")),
            old_activity_count,
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)