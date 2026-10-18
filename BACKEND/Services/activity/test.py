"""PostgreSQL integration tests for activity Services.

Run from the project root:
    python -m BACKEND.Services.activity.test

Requires the existing OpsPilot schema and activity Operations.
Uses real PostgreSQL records, not mocked database calls.
"""

from __future__ import annotations

import unittest
from typing import Any
from uuid import UUID

from BACKEND.Postgres.gateway import get_connection
from BACKEND.Postgres.Operations.activity.get_activity_by_id import (
    get_activity_by_id as get_activity_operation,
)
from BACKEND.Postgres.Operations.work_items.get_work_item_by_id import (
    get_work_item_by_id,
)
from BACKEND.Services.activity.create_activity import create_activity
from BACKEND.Services.activity.get_activity_by_id import (
    get_activity_by_id,
)
from BACKEND.Services.activity.get_team_activity import get_team_activity
from BACKEND.Services.activity.get_user_activity import get_user_activity
from BACKEND.Services.activity.get_work_item_activity import (
    get_work_item_activity,
)
from BACKEND.Services.work_management.test import WorkItemTestFixture


class RollbackProbe(Exception):
    """Force a caller-owned PostgreSQL transaction to roll back."""


def response_data(response):
    """Extract successful ServiceResponse data."""
    if not getattr(response, "success", False):
        raise AssertionError(
            "Expected successful ServiceResponse; "
            f"HTTP={getattr(response, 'http_status', None)}, "
            f"error={getattr(response, 'error', None)!r}"
        )

    return response.outputs.data


class ActivityServicesIntegrationTests(
    WorkItemTestFixture,
    unittest.TestCase,
):
    """Validate activity Services against persisted PostgreSQL state."""

    def _create_event(
        self,
        work_item_id: UUID,
        *,
        action: str = "status_changed",
    ) -> dict[str, Any]:
        response = create_activity(
            actor_user_id=self.actor_id,
            work_item_id=work_item_id,
            action=action,
            details={
                "test_marker": self.marker,
                "source": "activity_service_integration_test",
            },
        )
        return response_data(response)["activity"]

    def _activity_count(
        self,
        *,
        work_item_id: UUID,
        action: str | None = None,
    ) -> int:
        query = """
            SELECT COUNT(*)
            FROM work_item_activity
            WHERE work_item_id = %s
        """
        parameters: list[Any] = [work_item_id]

        if action is not None:
            query += " AND action = %s"
            parameters.append(action)

        with get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(query, tuple(parameters))
                return cursor.fetchone()[0]

    def test_create_activity_persists_to_postgresql(self):
        item = self._create_item("Activity Create")
        work_item_id = UUID(item["id"])

        event = self._create_event(
            work_item_id,
            action="created",
        )

        # Verify with the underlying Operation, independently of the Service.
        stored = get_activity_operation(UUID(event["id"]))

        self.assertIsNotNone(stored)
        self.assertEqual(stored["work_item_id"], work_item_id)
        self.assertEqual(stored["actor_id"], self.actor_id)
        self.assertEqual(stored["action"], "created")
        self.assertEqual(
            stored["details"]["test_marker"],
            self.marker,
        )
        self.assertIsNotNone(stored["created_at"])

    def test_get_activity_by_id_enforces_team_access(self):
        item = self._create_item("Activity Access")
        event = self._create_event(UUID(item["id"]))

        allowed = get_activity_by_id(
            actor_user_id=self.actor_id,
            activity_id=event["id"],
        )
        data = response_data(allowed)

        self.assertEqual(data["activity"]["id"], event["id"])

        denied = get_activity_by_id(
            actor_user_id=self.outsider_id,
            activity_id=event["id"],
        )

        self.assertFalse(denied.success)
        self.assertEqual(denied.http_status, 403)

    def test_work_item_activity_filters_and_paginates(self):
        item = self._create_item("Activity Pagination")
        work_item_id = UUID(item["id"])

        self._create_event(work_item_id, action="priority_changed")
        self._create_event(work_item_id, action="priority_changed")
        self._create_event(work_item_id, action="status_changed")

        first_response = get_work_item_activity(
            actor_user_id=self.actor_id,
            work_item_id=work_item_id,
            action="priority_changed",
            limit=1,
            offset=0,
        )
        first = response_data(first_response)

        second_response = get_work_item_activity(
            actor_user_id=self.actor_id,
            work_item_id=work_item_id,
            action="priority_changed",
            limit=1,
            offset=1,
        )
        second = response_data(second_response)

        self.assertEqual(first["total"], 2)
        self.assertEqual(second["total"], 2)
        self.assertEqual(len(first["items"]), 1)
        self.assertEqual(len(second["items"]), 1)
        self.assertNotEqual(
            first["items"][0]["id"],
            second["items"][0]["id"],
        )
        self.assertEqual(
            first["items"][0]["action"],
            "priority_changed",
        )

    def test_user_activity_is_visible_within_current_team_scope(self):
        item = self._create_item("User Feed")
        event = self._create_event(
            UUID(item["id"]),
            action="user_feed_test",
        )

        response = get_user_activity(
            actor_user_id=self.actor_id,
            limit=100,
            offset=0,
            action="user_feed_test",
        )
        data = response_data(response)

        returned_ids = {row["id"] for row in data["items"]}
        self.assertIn(event["id"], returned_ids)
        self.assertEqual(data["total"], 1)

    def test_user_cannot_inspect_another_users_activity_without_permission(self):
        item = self._create_item("User Feed Authorization")
        self._create_event(
            UUID(item["id"]),
            action="private_feed_test",
        )

        response = get_user_activity(
            actor_user_id=self.outsider_id,
            user_id=self.actor_id,
            action="private_feed_test",
        )

        self.assertFalse(response.success)
        self.assertEqual(response.http_status, 403)

    def test_team_activity_returns_only_the_requested_team(self):
        item = self._create_item("Team Feed")
        work_item_id = UUID(item["id"])

        event = self._create_event(
            work_item_id,
            action="team_feed_test",
        )

        response = get_team_activity(
            actor_user_id=self.actor_id,
            team_id=self.team_id,
            action="team_feed_test",
            limit=100,
            offset=0,
        )
        data = response_data(response)

        self.assertEqual(data["total"], 1)
        self.assertEqual(len(data["items"]), 1)
        self.assertEqual(data["items"][0]["id"], event["id"])
        self.assertEqual(
            data["items"][0]["work_item_id"],
            str(work_item_id),
        )

        forbidden = get_team_activity(
            actor_user_id=self.outsider_id,
            team_id=self.team_id,
            action="team_feed_test",
        )

        self.assertFalse(forbidden.success)
        self.assertEqual(forbidden.http_status, 403)

    def test_activity_creation_rolls_back_with_caller_transaction(self):
        item = self._create_item("Activity Rollback")
        work_item_id = UUID(item["id"])

        before_count = self._activity_count(
            work_item_id=work_item_id,
            action="rollback_probe",
        )

        try:
            with get_connection() as connection:
                response = create_activity(
                    actor_user_id=self.actor_id,
                    work_item_id=work_item_id,
                    action="rollback_probe",
                    details={"marker": self.marker},
                    connection=connection,
                )

                response_data(response)
                raise RollbackProbe()

        except RollbackProbe:
            pass

        after_count = self._activity_count(
            work_item_id=work_item_id,
            action="rollback_probe",
        )

        self.assertEqual(
            after_count,
            before_count,
            "Activity must roll back when the caller's transaction rolls back.",
        )

    def test_invalid_activity_details_are_rejected(self):
        item = self._create_item("Activity Invalid Details")
        work_item_id = UUID(item["id"])

        before_count = self._activity_count(work_item_id=work_item_id)

        response = create_activity(
            actor_user_id=self.actor_id,
            work_item_id=work_item_id,
            action="invalid_details_test",
            details={"invalid": object()},
        )

        self.assertFalse(response.success)
        self.assertEqual(response.http_status, 400)
        self.assertEqual(
            self._activity_count(work_item_id=work_item_id),
            before_count,
        )

    def test_activity_services_reject_invalid_pagination(self):
        item = self._create_item("Activity Invalid Pagination")

        response = get_work_item_activity(
            actor_user_id=self.actor_id,
            work_item_id=item["id"],
            limit=0,
        )

        self.assertFalse(response.success)
        self.assertEqual(response.http_status, 400)

    def test_activity_does_not_mutate_the_work_item(self):
        item = self._create_item("Activity Read Only")
        work_item_id = UUID(item["id"])
        before = get_work_item_by_id(work_item_id)

        self._create_event(
            work_item_id,
            action="observation_recorded",
        )

        after = get_work_item_by_id(work_item_id)

        self.assertEqual(before["id"], after["id"])
        self.assertEqual(before["status"], after["status"])
        self.assertEqual(before["priority"], after["priority"])
        self.assertEqual(before["assignee_id"], after["assignee_id"])


if __name__ == "__main__":
    unittest.main(verbosity=2)