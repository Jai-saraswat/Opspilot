"""PostgreSQL concurrency tests for work-item claiming.

Run:
    python -m BACKEND.Services.work_management.concurrency_test

Use only a disposable development/test database.
"""

from __future__ import annotations

import unittest
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import UUID

from BACKEND.Postgres.gateway import get_connection
from BACKEND.Postgres.Operations.work_items.claim_work_item_if_unassigned import (
    claim_work_item_if_unassigned,
)
from BACKEND.Postgres.Operations.work_items.get_work_item_by_id import (
    get_work_item_by_id,
)
from BACKEND.Services.work_management.claim_work_item import claim_work_item
from BACKEND.Services.work_management.test import WorkItemTestFixture


class WorkItemConcurrencyTests(
    WorkItemTestFixture,
    unittest.TestCase,
):
    """Prove only one concurrent claim can succeed."""

    def _claim_activity_count(self, work_item_id: UUID) -> int:
        with get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT COUNT(*)
                    FROM work_item_activity
                    WHERE work_item_id = %s
                      AND action = 'work_item_claimed'
                    """,
                    (work_item_id,),
                )
                return cursor.fetchone()[0]

    def test_database_conditional_claim_has_exactly_one_winner(self):
        item = self._create_item("Concurrent Database Claim")
        item_id = UUID(item["id"])

        original = get_work_item_by_id(item_id)
        self.assertIsNotNone(original)
        self.assertIsNone(original["assignee_id"])
        original_timestamp = original["updated_at"]

        barrier = Barrier(2)

        def claim_at_database_level(assignee_id: UUID):
            barrier.wait(timeout=10)

            # Each concurrent worker owns a separate PostgreSQL connection.
            with get_connection() as connection:
                return claim_work_item_if_unassigned(
                    item_id,
                    assignee_id,
                    expected_updated_at=original_timestamp,
                    connection=connection,
                )

        with ThreadPoolExecutor(max_workers=2) as executor:
            future_a = executor.submit(
                claim_at_database_level,
                self.actor_id,
            )
            future_b = executor.submit(
                claim_at_database_level,
                self.member_id,
            )

            result_a = future_a.result(timeout=30)
            result_b = future_b.result(timeout=30)

        results = [result_a, result_b]
        winners = [result for result in results if result is not None]
        losers = [result for result in results if result is None]

        self.assertEqual(len(winners), 1)
        self.assertEqual(len(losers), 1)

        stored = self._fetch_item_row(item_id)
        self.assertIsNotNone(stored)
        self.assertEqual(
            stored["assignee_id"],
            winners[0]["assignee_id"],
        )

        # Direct Operation calls do not execute the Service's activity logic.
        # Therefore this low-level test must not create claim events.
        self.assertEqual(self._claim_activity_count(item_id), 0)

    def test_concurrent_service_claims_create_one_claim_event(self):
        item = self._create_item("Concurrent Service Claim")
        item_id = UUID(item["id"])

        original = get_work_item_by_id(item_id)
        self.assertIsNotNone(original)
        original_timestamp = original["updated_at"]

        barrier = Barrier(2)

        def claim_through_service(actor_id: UUID):
            barrier.wait(timeout=10)

            return claim_work_item(
                actor_user_id=actor_id,
                work_item_id=item_id,
                expected_updated_at=original_timestamp,
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            future_a = executor.submit(
                claim_through_service,
                self.actor_id,
            )
            future_b = executor.submit(
                claim_through_service,
                self.member_id,
            )

            response_a = future_a.result(timeout=30)
            response_b = future_b.result(timeout=30)

        responses = [response_a, response_b]
        winners = [response for response in responses if response.success]
        conflicts = [
            response
            for response in responses
            if (
                not response.success
                and response.http_status == 409
            )
        ]

        self.assertEqual(
            len(winners),
            1,
            "Only one Service claim can succeed.",
        )
        self.assertEqual(
            len(conflicts),
            1,
            "The competing Service claim must receive HTTP 409.",
        )

        stored = self._fetch_item_row(item_id)
        self.assertIsNotNone(stored)
        self.assertIn(
            stored["assignee_id"],
            {self.actor_id, self.member_id},
        )

        # Exactly one successful Service claim is audited.
        self.assertEqual(self._claim_activity_count(item_id), 1)

        events = self._activity_rows(
            item_id,
            "work_item_claimed",
        )
        self.assertEqual(events[0]["actor_id"], stored["assignee_id"])

    def test_stale_claim_cannot_overwrite_assignee_or_create_event(self):
        item = self._create_item("Stale Claim")
        item_id = UUID(item["id"])

        original = get_work_item_by_id(item_id)
        original_timestamp = original["updated_at"]

        first = claim_work_item(
            actor_user_id=self.actor_id,
            work_item_id=item_id,
            expected_updated_at=original_timestamp,
        )
        self.assertTrue(first.success)

        # A second request reuses the now-stale timestamp.
        second = claim_work_item(
            actor_user_id=self.member_id,
            work_item_id=item_id,
            expected_updated_at=original_timestamp,
        )

        self.assertFalse(second.success)
        self.assertEqual(second.http_status, 409)

        stored = self._fetch_item_row(item_id)
        self.assertIsNotNone(stored)
        self.assertEqual(stored["assignee_id"], self.actor_id)

        # Only the initial successful claim should have an activity record.
        self.assertEqual(self._claim_activity_count(item_id), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)