"""PostgreSQL integration tests for approval Services.

Run from the project root:
    python -m BACKEND.Services.approvals.test

Uses the actual OpsPilot PostgreSQL database, not mocked database calls.
Run only against a disposable development/test database.
"""

from __future__ import annotations

import unittest
from unittest.mock import patch
from uuid import UUID

from psycopg.rows import dict_row

from BACKEND.Postgres.gateway import get_connection
from BACKEND.Postgres.Operations.activity.errors import ActivityDatabaseError
from BACKEND.Postgres.Operations.approvals.get_approval_request_by_id import (
    get_approval_request_by_id as get_approval_operation,
)
from BACKEND.Postgres.Operations.work_items.get_work_item_by_id import (
    get_work_item_by_id,
)
from BACKEND.Services.work_management.change_work_item_status import (
    change_work_item_status,
)
from BACKEND.Services.work_management.test import (
    WorkItemTestFixture,
    response_data,
)
from BACKEND.Services.approvals.assign_approval_approver import (
    assign_approval_approver,
)
from BACKEND.Services.approvals.create_approval_request import (
    create_approval_request,
)
from BACKEND.Services.approvals.get_approval_request import (
    get_approval_request,
)
from BACKEND.Services.approvals.get_pending_approvals import (
    get_pending_approvals,
)
from BACKEND.Services.approvals.list_user_approval_requests import (
    get_user_approval_requests,
)
from BACKEND.Services.approvals.list_work_item_approvals import (
    get_work_item_approvals,
)
from BACKEND.Services.approvals.retry_approval_request import (
    retry_approval_request,
)
from BACKEND.Services.approvals.review_approval_request import (
    review_approval_request,
)


class ApprovalServicesIntegrationTests(
    WorkItemTestFixture,
    unittest.TestCase,
):
    """Test complete approval workflows against persisted database state."""

    def setUp(self):
        super().setUp()

        # The existing work-management fixture initially makes this user a
        # regular member. For approval tests, make the member an approver.
        with get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE team_memberships
                    SET role = 'approver'
                    WHERE team_id = %s AND user_id = %s
                    """,
                    (self.team_id, self.member_id),
                )

    def _start_item(self, label: str = "Approval Test Item") -> dict:
        """Create a work item and move it to in_progress via the Service."""
        item = self._create_item(label)
        before = self._fetch_item_row(UUID(item["id"]))

        response = change_work_item_status(
            actor_user_id=self.actor_id,
            work_item_id=item["id"],
            status="in_progress",
            expected_updated_at=before["updated_at"],
        )
        response_data(response)

        return item

    def _approval_row(self, approval_id: UUID) -> dict | None:
        with get_connection() as connection:
            with connection.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    """
                    SELECT
                        id,
                        work_item_id,
                        requested_by,
                        approver_id,
                        status,
                        decision_reason,
                        requested_at,
                        decided_at
                    FROM work_item_approval_requests
                    WHERE id = %s
                    """,
                    (approval_id,),
                )
                row = cursor.fetchone()

        return dict(row) if row is not None else None

    def _activity_rows(
        self,
        work_item_id: UUID,
        action: str | None = None,
    ) -> list[dict]:
        query = """
            SELECT id, work_item_id, actor_id, action, details, created_at
            FROM work_item_activity
            WHERE work_item_id = %s
        """
        parameters: list = [work_item_id]

        if action is not None:
            query += " AND action = %s"
            parameters.append(action)

        query += " ORDER BY created_at ASC, id ASC"

        with get_connection() as connection:
            with connection.cursor(row_factory=dict_row) as cursor:
                cursor.execute(query, tuple(parameters))
                return [dict(row) for row in cursor.fetchall()]

    def _create_pending_request(self, label: str = "Approval Item") -> tuple[dict, dict]:
        item = self._start_item(label)

        response = create_approval_request(
            actor_user_id=self.actor_id,
            work_item_id=item["id"],
            approver_id=self.member_id,
        )
        request = response_data(response)["approval_request"]

        stored_item = self._fetch_item_row(UUID(item["id"]))
        self.assertEqual(stored_item["status"], "pending_approval")

        return item, request

    # ---------------------------------------------------------------
    # Submission and validation
    # ---------------------------------------------------------------

    def test_submit_creates_request_updates_item_and_records_activity(self):
        item, request = self._create_pending_request("Submit Test")

        stored_request = self._approval_row(UUID(request["id"]))
        stored_item = self._fetch_item_row(UUID(item["id"]))

        self.assertIsNotNone(stored_request)
        self.assertEqual(stored_request["status"], "pending")
        self.assertEqual(stored_request["requested_by"], self.actor_id)
        self.assertEqual(stored_request["approver_id"], self.member_id)

        self.assertEqual(stored_item["status"], "pending_approval")
        self.assertIsNone(stored_item["completed_at"])

        events = self._activity_rows(
            UUID(item["id"]),
            "approval_requested",
        )
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["actor_id"], self.actor_id)
        self.assertEqual(
            events[0]["details"]["approval_request_id"],
            request["id"],
        )

    def test_new_submission_rejected_when_a_pending_request_exists(self):
        item, request = self._create_pending_request("Duplicate Request")

        duplicate = create_approval_request(
            actor_user_id=self.actor_id,
            work_item_id=item["id"],
            approver_id=self.member_id,
        )

        self.assertFalse(duplicate.success)
        self.assertEqual(duplicate.http_status, 409)

        with get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT COUNT(*)
                    FROM work_item_approval_requests
                    WHERE work_item_id = %s AND status = 'pending'
                    """,
                    (UUID(item["id"]),),
                )
                self.assertEqual(cursor.fetchone()[0], 1)

    def test_requester_cannot_approve_their_own_request(self):
        item, request = self._create_pending_request("Self Approval")

        response = review_approval_request(
            actor_user_id=self.actor_id,
            approval_request_id=request["id"],
            decision="approved",
        )

        self.assertFalse(response.success)
        self.assertEqual(response.http_status, 403)

        stored_request = self._approval_row(UUID(request["id"]))
        stored_item = self._fetch_item_row(UUID(item["id"]))

        self.assertEqual(stored_request["status"], "pending")
        self.assertEqual(stored_item["status"], "pending_approval")

    def test_nonapprover_cannot_review_request(self):
        item, request = self._create_pending_request("Unauthorized Review")

        response = review_approval_request(
            actor_user_id=self.outsider_id,
            approval_request_id=request["id"],
            decision="approved",
        )

        self.assertFalse(response.success)
        self.assertEqual(response.http_status, 403)

        stored_request = self._approval_row(UUID(request["id"]))
        self.assertEqual(stored_request["status"], "pending")

    # ---------------------------------------------------------------
    # The critical rejected -> retry lifecycle
    # ---------------------------------------------------------------

    def test_rejection_stays_rejected_until_explicit_retry(self):
        item, request = self._create_pending_request("Reject and Retry")
        request_id = UUID(request["id"])
        work_item_id = UUID(item["id"])

        rejected = review_approval_request(
            actor_user_id=self.member_id,
            approval_request_id=request_id,
            decision="rejected",
            decision_reason="The evidence is incomplete.",
        )
        response_data(rejected)

        rejected_row = self._approval_row(request_id)
        after_rejection = self._fetch_item_row(work_item_id)

        self.assertEqual(rejected_row["status"], "rejected")
        self.assertEqual(
            rejected_row["decision_reason"],
            "The evidence is incomplete.",
        )
        self.assertIsNotNone(rejected_row["decided_at"])
        self.assertEqual(after_rejection["status"], "in_progress")
        self.assertIsNone(after_rejection["completed_at"])

        rejection_events = self._activity_rows(
            work_item_id,
            "approval_rejected",
        )
        self.assertEqual(len(rejection_events), 1)
        self.assertEqual(
            rejection_events[0]["details"]["decision_reason"],
            "The evidence is incomplete.",
        )
        self.assertEqual(rejection_events[0]["actor_id"], self.member_id)

        # The rejected request cannot be reviewed again before a retry.
        second_review = review_approval_request(
            actor_user_id=self.member_id,
            approval_request_id=request_id,
            decision="approved",
        )
        self.assertFalse(second_review.success)
        self.assertEqual(second_review.http_status, 409)

        still_rejected = self._approval_row(request_id)
        self.assertEqual(still_rejected["status"], "rejected")

        # Explicit retry reopens the same row.
        retry = retry_approval_request(
            actor_user_id=self.actor_id,
            approval_request_id=request_id,
        )
        retry_data = response_data(retry)["approval_request"]

        self.assertEqual(retry_data["id"], str(request_id))
        self.assertEqual(retry_data["status"], "pending")

        retried_row = self._approval_row(request_id)
        retried_item = self._fetch_item_row(work_item_id)

        self.assertEqual(retried_row["id"], request_id)
        self.assertEqual(retried_row["status"], "pending")
        self.assertIsNone(retried_row["decision_reason"])
        self.assertIsNone(retried_row["decided_at"])
        self.assertEqual(retried_item["status"], "pending_approval")

        # The original rejection event was not overwritten or removed.
        rejection_events_after_retry = self._activity_rows(
            work_item_id,
            "approval_rejected",
        )
        retry_events = self._activity_rows(
            work_item_id,
            "approval_retried",
        )

        self.assertEqual(len(rejection_events_after_retry), 1)
        self.assertEqual(len(retry_events), 1)
        self.assertEqual(
            retry_events[0]["details"]["previous_decision_reason"],
            "The evidence is incomplete.",
        )

    def test_retried_request_can_later_be_approved(self):
        item, request = self._create_pending_request("Retry Then Approve")
        request_id = UUID(request["id"])
        work_item_id = UUID(item["id"])

        rejected = review_approval_request(
            actor_user_id=self.member_id,
            approval_request_id=request_id,
            decision="rejected",
            decision_reason="Needs correction.",
        )
        response_data(rejected)

        retried = retry_approval_request(
            actor_user_id=self.actor_id,
            approval_request_id=request_id,
        )
        response_data(retried)

        approved = review_approval_request(
            actor_user_id=self.member_id,
            approval_request_id=request_id,
            decision="approved",
            decision_reason="Corrections accepted.",
        )
        response_data(approved)

        stored_request = self._approval_row(request_id)
        stored_item = self._fetch_item_row(work_item_id)

        self.assertEqual(stored_request["status"], "approved")
        self.assertEqual(
            stored_request["decision_reason"],
            "Corrections accepted.",
        )
        self.assertIsNotNone(stored_request["decided_at"])

        self.assertEqual(stored_item["status"], "resolved")
        self.assertIsNotNone(stored_item["completed_at"])

        actions = [
            event["action"]
            for event in self._activity_rows(work_item_id)
        ]
        self.assertIn("approval_rejected", actions)
        self.assertIn("approval_retried", actions)
        self.assertIn("approval_approved", actions)

    def test_only_original_requester_can_retry(self):
        item, request = self._create_pending_request("Retry Authorization")

        rejected = review_approval_request(
            actor_user_id=self.member_id,
            approval_request_id=request["id"],
            decision="rejected",
            decision_reason="Please revise.",
        )
        response_data(rejected)

        forbidden = retry_approval_request(
            actor_user_id=self.member_id,
            approval_request_id=request["id"],
        )

        self.assertFalse(forbidden.success)
        self.assertEqual(forbidden.http_status, 403)

        stored = self._approval_row(UUID(request["id"]))
        self.assertEqual(stored["status"], "rejected")

    # ---------------------------------------------------------------
    # Assignment, read/list services and pending queue
    # ---------------------------------------------------------------

    def test_assign_approver_and_record_activity(self):
        item = self._start_item("Assigner Test")

        request_response = create_approval_request(
            actor_user_id=self.actor_id,
            work_item_id=item["id"],
        )
        request = response_data(request_response)["approval_request"]

        response = assign_approval_approver(
            actor_user_id=self.actor_id,
            approval_request_id=request["id"],
            approver_id=self.member_id,
        )
        data = response_data(response)["approval_request"]

        self.assertEqual(data["approver_id"], str(self.member_id))

        stored = self._approval_row(UUID(request["id"]))
        self.assertEqual(stored["approver_id"], self.member_id)

        events = self._activity_rows(
            UUID(item["id"]),
            "approval_approver_assigned",
        )
        self.assertEqual(len(events), 1)
        self.assertEqual(
            events[0]["details"]["new_approver_id"],
            str(self.member_id),
        )

    def test_pending_queue_only_contains_eligible_assigned_requests(self):
        item, request = self._create_pending_request("Queue Item")

        response = get_pending_approvals(
            actor_user_id=self.member_id,
            limit=100,
            offset=0,
        )
        data = response_data(response)

        self.assertIn(
            request["id"],
            {row["id"] for row in data["items"]},
        )

        outsider_response = get_pending_approvals(
            actor_user_id=self.outsider_id,
            limit=100,
            offset=0,
        )
        outsider_data = response_data(outsider_response)

        self.assertEqual(outsider_data["items"], [])
        self.assertEqual(outsider_data["total"], 0)

    def test_get_approval_request_and_work_item_history_are_authorized(self):
        item, request = self._create_pending_request("Read Test")

        allowed = get_approval_request(
            actor_user_id=self.actor_id,
            approval_request_id=request["id"],
        )
        self.assertEqual(
            response_data(allowed)["approval_request"]["id"],
            request["id"],
        )

        forbidden = get_approval_request(
            actor_user_id=self.outsider_id,
            approval_request_id=request["id"],
        )
        self.assertFalse(forbidden.success)
        self.assertEqual(forbidden.http_status, 403)

        history = get_work_item_approvals(
            actor_user_id=self.actor_id,
            work_item_id=item["id"],
            limit=100,
        )
        history_data = response_data(history)

        self.assertEqual(history_data["total"], 1)
        self.assertEqual(history_data["items"][0]["id"], request["id"])

    def test_user_approval_request_history_is_persisted_and_listable(self):
        _, request = self._create_pending_request("User History")

        response = get_user_approval_requests(
            actor_user_id=self.actor_id,
            limit=100,
            offset=0,
        )
        data = response_data(response)

        self.assertIn(
            request["id"],
            {row["id"] for row in data["items"]},
        )

    # ---------------------------------------------------------------
    # Atomicity and invalid transitions
    # ---------------------------------------------------------------

    def test_activity_failure_rolls_back_request_and_status_change(self):
        item = self._start_item("Approval Rollback")
        work_item_id = UUID(item["id"])

        with patch(
            "BACKEND.Services.approvals.create_approval_request."
            "record_work_item_activity",
            side_effect=ActivityDatabaseError(
                "simulated activity insert failure"
            ),
        ):
            response = create_approval_request(
                actor_user_id=self.actor_id,
                work_item_id=item["id"],
                approver_id=self.member_id,
            )

        self.assertFalse(response.success)
        self.assertEqual(response.http_status, 500)

        stored_item = self._fetch_item_row(work_item_id)
        self.assertEqual(stored_item["status"], "in_progress")

        with get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT COUNT(*)
                    FROM work_item_approval_requests
                    WHERE work_item_id = %s
                    """,
                    (work_item_id,),
                )
                self.assertEqual(cursor.fetchone()[0], 0)

        self.assertEqual(
            len(
                self._activity_rows(
                    work_item_id,
                    "approval_requested",
                )
            ),
            0,
        )

    def test_retry_of_non_rejected_request_is_rejected(self):
        item, request = self._create_pending_request("Invalid Retry")

        response = retry_approval_request(
            actor_user_id=self.actor_id,
            approval_request_id=request["id"],
        )

        self.assertFalse(response.success)
        self.assertEqual(response.http_status, 409)

        stored = self._approval_row(UUID(request["id"]))
        self.assertEqual(stored["status"], "pending")

    def test_decision_cannot_be_overwritten_after_rejection(self):
        item, request = self._create_pending_request("Duplicate Decision")

        first = review_approval_request(
            actor_user_id=self.member_id,
            approval_request_id=request["id"],
            decision="rejected",
            decision_reason="Rejected once.",
        )
        response_data(first)

        second = review_approval_request(
            actor_user_id=self.member_id,
            approval_request_id=request["id"],
            decision="approved",
        )

        self.assertFalse(second.success)
        self.assertEqual(second.http_status, 409)

        stored = self._approval_row(UUID(request["id"]))
        self.assertEqual(stored["status"], "rejected")
        self.assertEqual(stored["decision_reason"], "Rejected once.")


if __name__ == "__main__":
    unittest.main(verbosity=2)