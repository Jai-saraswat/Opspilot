"""PostgreSQL integration tests for OpsPilot work-item Operations.

Run from the project root:
    python -m BACKEND.Postgres.Operations.work_items.test

Use a development/test database, never production.
Tests create disposable users, teams, and work items.
"""

from __future__ import annotations

import inspect
import unittest
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from psycopg.rows import dict_row

from BACKEND.Postgres.gateway import get_connection
from BACKEND.Postgres.Operations.work_items import errors as work_item_errors

from BACKEND.Postgres.Operations.work_items.create_work_item import (
    create_work_item,
)
from BACKEND.Postgres.Operations.work_items.get_work_item_by_id import (
    get_work_item_by_id,
)
from BACKEND.Postgres.Operations.work_items.list_work_items import (
    list_work_items,
)
from BACKEND.Postgres.Operations.work_items.update_work_item import (
    update_work_item,
)
from BACKEND.Postgres.Operations.work_items.assign_work_item import (
    assign_work_item,
)
from BACKEND.Postgres.Operations.work_items.claim_work_item_if_unassigned import (
    claim_work_item_if_unassigned,
)
from BACKEND.Postgres.Operations.work_items.update_work_item_status import (
    update_work_item_status,
)
from BACKEND.Postgres.Operations.work_items.update_work_item_priority import (
    update_work_item_priority,
)


class RollbackProbe(Exception):
    """Force a caller-owned transaction to roll back."""


class WorkItemsOperationsIntegrationTests(unittest.TestCase):
    """Exercise work-item Operations against PostgreSQL."""

    ARGUMENT_ALIASES = {
        "work_item_id": (
            "work_item_id",
            "item_id",
            "id",
        ),
        "title": ("title",),
        "description": ("description",),
        "type": (
            "type",
            "work_item_type",
            "item_type",
        ),
        "status": (
            "status",
            "new_status",
            "target_status",
        ),
        "priority": (
            "priority",
            "new_priority",
            "target_priority",
        ),
        "team_id": ("team_id",),
        "created_by": (
            "created_by",
            "creator_id",
        ),
        "assignee_id": (
            "assignee_id",
            "new_assignee_id",
            "target_assignee_id",
            "assigned_to",
            "user_id",
            "claimant_id",
        ),
        "expected_assignee_id": (
            "expected_assignee_id",
            "expected_current_assignee_id",
            "current_assignee_id",
            "expected_assignee",
        ),
        "expected_updated_at": (
            "expected_updated_at",
            "expected_timestamp",
            "expected_updated_at_marker",
            "current_updated_at",
        ),
        "assigned_by": (
            "assigned_by",
            "actor_id",
            "performed_by",
            "assigned_by_user_id",
        ),
        "search": (
            "search",
            "query",
        ),
        "limit": (
            "limit",
            "page_size",
        ),
        "offset": ("offset",),
        "connection": ("connection",),
    }

    @classmethod
    def setUpClass(cls) -> None:
        """Verify PostgreSQL connectivity and required tables."""
        required_tables = (
            "users",
            "teams",
            "work_items",
            "work_item_activity",
            "work_item_approval_requests",
        )

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
                        "Refusing to run tests against a "
                        f"production-looking database: {cls.database_name!r}"
                    )

                for table_name in required_tables:
                    cursor.execute(
                        "SELECT to_regclass(%s) AS table_name",
                        (f"public.{table_name}",),
                    )
                    result = cursor.fetchone()

                    if result is None or result["table_name"] is None:
                        raise RuntimeError(
                            f"Required table public.{table_name} was not "
                            "found. Initialize the schema first."
                        )

        print(
            f"\nConnected to PostgreSQL database: {cls.database_name}"
        )

    def setUp(self) -> None:
        """Create disposable users and a team for each test."""
        self.marker = uuid4().hex
        self.created_user_ids: list[UUID] = []
        self.created_team_ids: list[UUID] = []
        self.created_work_item_ids: list[UUID] = []

        self.user_a = self._create_test_user("alpha")
        self.user_b = self._create_test_user("beta")
        self.team_a = self._create_test_team()

    def tearDown(self) -> None:
        """Remove only the work items, teams, and users owned by this test."""
        with get_connection() as connection:
            with connection.cursor() as cursor:
                for work_item_id in self.created_work_item_ids:
                    cursor.execute(
                        """
                        DELETE FROM work_item_activity
                        WHERE work_item_id = %s;
                        """,
                        (work_item_id,),
                    )
                    cursor.execute(
                        """
                        DELETE FROM work_item_approval_requests
                        WHERE work_item_id = %s;
                        """,
                        (work_item_id,),
                    )
                    cursor.execute(
                        """
                        DELETE FROM work_items
                        WHERE id = %s;
                        """,
                        (work_item_id,),
                    )

                for team_id in self.created_team_ids:
                    cursor.execute(
                        "DELETE FROM teams WHERE id = %s;",
                        (team_id,),
                    )

                for user_id in self.created_user_ids:
                    cursor.execute(
                        "DELETE FROM users WHERE id = %s;",
                        (user_id,),
                    )

    # =========================================================
    # OPERATION INVOCATION HELPER
    # =========================================================

    def _invoke(
        self,
        operation: Any,
        *,
        required: tuple[str, ...] = (),
        **values: Any,
    ) -> Any:
        """Invoke an operation using its actual accepted parameter names.

        Semantic parameter names are mapped to common naming variations.
        Unsupported optional values are omitted, but each semantic argument
        specified in `required` must be accepted by the operation.
        """
        signature = inspect.signature(operation)
        parameters = signature.parameters
        kwargs: dict[str, Any] = {}
        matched_semantics: set[str] = set()

        for semantic_name, value in values.items():
            aliases = self.ARGUMENT_ALIASES.get(
                semantic_name,
                (semantic_name,),
            )

            target_name = next(
                (
                    alias
                    for alias in aliases
                    if alias in parameters
                ),
                None,
            )

            if target_name is None:
                continue

            kwargs[target_name] = value
            matched_semantics.add(semantic_name)

        missing_semantics = set(required) - matched_semantics

        if missing_semantics:
            raise AssertionError(
                f"{operation.__name__} does not expose required semantic "
                f"arguments {sorted(missing_semantics)}. Actual parameters: "
                f"{list(parameters)}"
            )

        missing_parameters = [
            parameter.name
            for parameter in parameters.values()
            if parameter.kind
            in (
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
                inspect.Parameter.KEYWORD_ONLY,
            )
            and parameter.default is inspect.Parameter.empty
            and parameter.name not in kwargs
        ]

        if missing_parameters:
            raise AssertionError(
                f"Missing required parameters for {operation.__name__}: "
                f"{missing_parameters}. Actual parameters: "
                f"{list(parameters)}"
            )

        return operation(**kwargs)

    @classmethod
    def _extract_rows(cls, result: Any) -> list[dict[str, Any]]:
        """Normalize common list-operation return formats."""
        if isinstance(result, list):
            if not all(isinstance(row, dict) for row in result):
                raise AssertionError(
                    "List operation returned non-dictionary entries."
                )
            return result

        if isinstance(result, tuple) and result:
            if isinstance(result[0], list):
                return cls._extract_rows(result[0])

        if isinstance(result, dict):
            if "id" in result and "team_id" in result:
                return [result]

            for key in (
                "work_items",
                "items",
                "records",
                "results",
                "data",
            ):
                value = result.get(key)

                if isinstance(value, list):
                    if not all(isinstance(row, dict) for row in value):
                        raise AssertionError(
                            f"Result key {key!r} contains invalid entries."
                        )
                    return value

                if isinstance(value, dict):
                    return cls._extract_rows(value)

        raise AssertionError(
            "Unexpected list-operation result type: "
            f"{type(result).__name__}"
        )

    # =========================================================
    # DATABASE FIXTURE HELPERS
    # =========================================================

    def _create_test_user(self, suffix: str) -> UUID:
        """Insert a disposable user."""
        email = (
            f"workitem-test-{self.marker}-{suffix}@example.invalid"
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
                        f"Work Item Test {suffix} {self.marker}",
                        email,
                        f"test-only-hash-{uuid4().hex}",
                    ),
                )
                user_id = UUID(str(cursor.fetchone()[0]))

        self.created_user_ids.append(user_id)
        return user_id

    def _create_test_team(self) -> UUID:
        """Insert a disposable team."""
        name = f"WorkItemTeam-{self.marker[:12]}"

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
                        "Temporary work-item integration-test team.",
                        self.user_a,
                    ),
                )
                team_id = UUID(str(cursor.fetchone()[0]))

        self.created_team_ids.append(team_id)
        return team_id

    def _fetch_work_item(
        self,
        work_item_id: UUID,
    ) -> dict[str, Any] | None:
        """Read a work item directly from PostgreSQL."""
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
                    WHERE id = %s;
                    """,
                    (work_item_id,),
                )
                row = cursor.fetchone()

        return dict(row) if row is not None else None

    def _create_test_work_item(
        self,
        suffix: str = "item",
        *,
        item_type: str = "investigation",
    ) -> dict[str, Any]:
        """Create an item through the operation, then verify it in PostgreSQL."""
        title = f"WI-{self.marker[:10]}-{suffix}"
        description = f"Integration test item {self.marker} {suffix}"

        self._invoke(
            create_work_item,
            required=(
                "title",
                "description",
                "type",
                "team_id",
                "created_by",
            ),
            title=title,
            description=description,
            type=item_type,
            team_id=self.team_a,
            created_by=self.user_a,
        )

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
                    WHERE title = %s AND team_id = %s;
                    """,
                    (title, self.team_a),
                )
                row = cursor.fetchone()

        if row is None:
            raise AssertionError(
                "create_work_item returned without persisting the item."
            )

        item = dict(row)
        item["id"] = UUID(str(item["id"]))
        self.created_work_item_ids.append(item["id"])

        return item

    # =========================================================
    # errors.py
    # =========================================================

    def test_work_item_errors_module_exposes_domain_exceptions(
        self,
    ) -> None:
        for name in (
            "InvalidWorkItemRecordError",
            "WorkItemRelatedRecordNotFoundError",
            "WorkItemDatabaseError",
        ):
            with self.subTest(exception=name):
                exception_type = getattr(work_item_errors, name)
                self.assertTrue(issubclass(exception_type, Exception))

    # =========================================================
    # create_work_item.py
    # =========================================================

    def test_create_work_item_persists_core_fields(self) -> None:
        item = self._create_test_work_item("persist")
        stored = self._fetch_work_item(item["id"])

        self.assertIsNotNone(stored)
        assert stored is not None

        self.assertEqual(stored["title"], item["title"])
        self.assertEqual(stored["description"], item["description"])
        self.assertEqual(stored["type"], "investigation")
        self.assertEqual(stored["status"], "open")
        self.assertEqual(stored["priority"], "medium")
        self.assertEqual(stored["team_id"], self.team_a)
        self.assertEqual(stored["created_by"], self.user_a)
        self.assertIsNone(stored["assignee_id"])
        self.assertIsNone(stored["completed_at"])
        self.assertIsNotNone(stored["created_at"])
        self.assertIsNotNone(stored["updated_at"])

    def test_create_work_item_supports_valid_types(self) -> None:
        for item_type in (
            "investigation",
            "action",
            "incident",
            "approval",
        ):
            with self.subTest(item_type=item_type):
                item = self._create_test_work_item(
                    f"type-{item_type}",
                    item_type=item_type,
                )
                self.assertEqual(item["type"], item_type)

    def test_create_work_item_rejects_blank_title(self) -> None:
        with self.assertRaises(
            work_item_errors.InvalidWorkItemRecordError
        ):
            self._invoke(
                create_work_item,
                required=(
                    "title",
                    "description",
                    "type",
                    "team_id",
                    "created_by",
                ),
                title="   ",
                description="A valid description for a negative test.",
                type="investigation",
                team_id=self.team_a,
                created_by=self.user_a,
            )

        with get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT COUNT(*)
                    FROM work_items
                    WHERE team_id = %s
                      AND created_by = %s
                      AND title = %s;
                    """,
                    (self.team_a, self.user_a, "   "),
                )
                self.assertEqual(cursor.fetchone()[0], 0)

    # =========================================================
    # get_work_item_by_id.py
    # =========================================================

    def test_get_work_item_by_id_returns_existing_item(self) -> None:
        item = self._create_test_work_item("get")

        result = self._invoke(
            get_work_item_by_id,
            required=("work_item_id",),
            work_item_id=item["id"],
        )

        self.assertIsNotNone(result)
        self.assertEqual(str(result["id"]), str(item["id"]))
        self.assertEqual(result["title"], item["title"])
        self.assertEqual(str(result["team_id"]), str(self.team_a))

    def test_get_work_item_by_id_returns_none_when_missing(self) -> None:
        result = self._invoke(
            get_work_item_by_id,
            required=("work_item_id",),
            work_item_id=uuid4(),
        )

        self.assertIsNone(result)

    # =========================================================
    # list_work_items.py
    # =========================================================

    def test_list_work_items_returns_items_for_requested_team(
        self,
    ) -> None:
        item_a = self._create_test_work_item("list-a")
        item_b = self._create_test_work_item("list-b")

        rows = self._extract_rows(
            self._invoke(
                list_work_items,
                team_id=self.team_a,
                limit=50,
                offset=0,
            )
        )

        returned_ids = {
            str(row["id"])
            for row in rows
        }

        self.assertIn(str(item_a["id"]), returned_ids)
        self.assertIn(str(item_b["id"]), returned_ids)

        self.assertTrue(
            all(
                str(row["team_id"]) == str(self.team_a)
                for row in rows
            ),
            "The listing returned an item from another team.",
        )

    def test_list_work_items_supports_pagination(self) -> None:
        created_items = [
            self._create_test_work_item(f"page-{index}")
            for index in range(3)
        ]

        page_one = self._extract_rows(
            self._invoke(
                list_work_items,
                team_id=self.team_a,
                limit=1,
                offset=0,
            )
        )
        page_two = self._extract_rows(
            self._invoke(
                list_work_items,
                team_id=self.team_a,
                limit=1,
                offset=1,
            )
        )

        self.assertEqual(len(page_one), 1)
        self.assertEqual(len(page_two), 1)

        first_id = str(page_one[0]["id"])
        second_id = str(page_two[0]["id"])

        self.assertNotEqual(
            first_id,
            second_id,
            "Adjacent pages returned the same item.",
        )

        fixture_ids = {
            str(item["id"])
            for item in created_items
        }

        self.assertIn(first_id, fixture_ids)
        self.assertIn(second_id, fixture_ids)

    # =========================================================
    # update_work_item.py
    # =========================================================

    def test_update_work_item_persists_title_and_description(
        self,
    ) -> None:
        item = self._create_test_work_item("update")

        new_title = f"Changed-{self.marker[:10]}"
        new_description = "Updated description from integration test."

        self._invoke(
            update_work_item,
            required=("work_item_id", "expected_updated_at", "title"),
            work_item_id=item["id"],
            expected_updated_at=item["updated_at"],
            title=new_title,
            description=new_description,
        )

        stored = self._fetch_work_item(item["id"])

        self.assertIsNotNone(stored)
        assert stored is not None

        self.assertEqual(stored["title"], new_title)
        self.assertEqual(stored["description"], new_description)

    def test_update_work_item_does_not_overwrite_stale_state(
        self,
    ) -> None:
        item = self._create_test_work_item("stale-update")
        original_title = item["title"]

        self._invoke(
            update_work_item,
            required=("work_item_id", "expected_updated_at", "title"),
            work_item_id=item["id"],
            expected_updated_at=datetime(
                2000, 1, 1, tzinfo=timezone.utc
            ),
            title=f"Stale-{self.marker[:10]}",
        )

        stored = self._fetch_work_item(item["id"])

        self.assertIsNotNone(stored)
        assert stored is not None
        self.assertEqual(
            stored["title"],
            original_title,
            "A stale update overwrote the current title.",
        )

    # =========================================================
    # claim_work_item_if_unassigned.py
    # =========================================================

    def test_claim_work_item_if_unassigned_assigns_first_claimant(
        self,
    ) -> None:
        item = self._create_test_work_item("claim")

        self._invoke(
            claim_work_item_if_unassigned,
            required=("work_item_id", "assignee_id", "expected_updated_at"),
            work_item_id=item["id"],
            assignee_id=self.user_a,
            expected_updated_at=item["updated_at"],
            assigned_by=self.user_a,
        )

        stored = self._fetch_work_item(item["id"])

        self.assertIsNotNone(stored)
        assert stored is not None
        self.assertEqual(stored["assignee_id"], self.user_a)

    def test_claim_work_item_if_unassigned_does_not_replace_claimant(
        self,
    ) -> None:
        item = self._create_test_work_item("claim-race")

        self._invoke(
            claim_work_item_if_unassigned,
            required=("work_item_id", "assignee_id", "expected_updated_at"),
            work_item_id=item["id"],
            assignee_id=self.user_a,
            expected_updated_at=item["updated_at"],
            assigned_by=self.user_a,
        )

        after_first_claim = self._fetch_work_item(item["id"])
        self.assertIsNotNone(after_first_claim)
        assert after_first_claim is not None
        self.assertEqual(after_first_claim["assignee_id"], self.user_a)

        # Reuse the original timestamp to simulate a competing stale claim.
        # A conditional claim can either return no updated row or raise the
        # operation's related-record domain error for a lost claim.
        try:
            self._invoke(
                claim_work_item_if_unassigned,
                required=(
                    "work_item_id",
                    "assignee_id",
                    "expected_updated_at",
                ),
                work_item_id=item["id"],
                assignee_id=self.user_b,
                expected_updated_at=item["updated_at"],
                assigned_by=self.user_b,
            )
        except work_item_errors.WorkItemRelatedRecordNotFoundError:
            pass

        after_second_claim = self._fetch_work_item(item["id"])

        self.assertIsNotNone(after_second_claim)
        assert after_second_claim is not None
        self.assertEqual(
            after_second_claim["assignee_id"],
            self.user_a,
            "A competing claim replaced the first claimant.",
        )

    # =========================================================
    # assign_work_item.py
    # =========================================================

    def test_assign_work_item_assigns_target_user(self) -> None:
        item = self._create_test_work_item("assign")

        self._invoke(
            assign_work_item,
            required=("work_item_id", "assignee_id"),
            work_item_id=item["id"],
            assignee_id=self.user_b,
            expected_assignee_id=None,
            expected_updated_at=item["updated_at"],
            assigned_by=self.user_a,
        )

        stored = self._fetch_work_item(item["id"])

        self.assertIsNotNone(stored)
        assert stored is not None
        self.assertEqual(stored["assignee_id"], self.user_b)

    def test_assign_work_item_can_reassign_item(self) -> None:
        item = self._create_test_work_item("reassign")

        self._invoke(
            assign_work_item,
            required=("work_item_id", "assignee_id"),
            work_item_id=item["id"],
            assignee_id=self.user_a,
            expected_assignee_id=None,
            expected_updated_at=item["updated_at"],
            assigned_by=self.user_a,
        )

        after_first_assignment = self._fetch_work_item(item["id"])
        self.assertIsNotNone(after_first_assignment)
        assert after_first_assignment is not None

        self._invoke(
            assign_work_item,
            required=("work_item_id", "assignee_id"),
            work_item_id=item["id"],
            assignee_id=self.user_b,
            expected_assignee_id=self.user_a,
            expected_updated_at=after_first_assignment["updated_at"],
            assigned_by=self.user_a,
        )

        stored = self._fetch_work_item(item["id"])

        self.assertIsNotNone(stored)
        assert stored is not None
        self.assertEqual(stored["assignee_id"], self.user_b)

    # =========================================================
    # update_work_item_status.py
    # =========================================================

    def test_update_work_item_status_persists_status(self) -> None:
        item = self._create_test_work_item("status")

        self._invoke(
            update_work_item_status,
            required=("work_item_id", "status", "expected_updated_at"),
            work_item_id=item["id"],
            status="in_progress",
            expected_updated_at=item["updated_at"],
        )

        stored = self._fetch_work_item(item["id"])

        self.assertIsNotNone(stored)
        assert stored is not None
        self.assertEqual(stored["status"], "in_progress")
        self.assertIsNone(stored["completed_at"])

    def test_resolving_work_item_sets_completed_at(self) -> None:
        item = self._create_test_work_item("resolve")

        self._invoke(
            update_work_item_status,
            required=("work_item_id", "status", "expected_updated_at"),
            work_item_id=item["id"],
            status="resolved",
            expected_updated_at=item["updated_at"],
        )

        stored = self._fetch_work_item(item["id"])

        self.assertIsNotNone(stored)
        assert stored is not None

        self.assertEqual(stored["status"], "resolved")
        self.assertIsNotNone(
            stored["completed_at"],
            "Resolving a work item must set completed_at.",
        )

    def test_stale_status_update_does_not_change_current_status(
        self,
    ) -> None:
        item = self._create_test_work_item("stale-status")

        self._invoke(
            update_work_item_status,
            required=("work_item_id", "status", "expected_updated_at"),
            work_item_id=item["id"],
            status="in_progress",
            expected_updated_at=datetime(
                2000, 1, 1, tzinfo=timezone.utc
            ),
        )

        stored = self._fetch_work_item(item["id"])

        self.assertIsNotNone(stored)
        assert stored is not None
        self.assertEqual(stored["status"], "open")

    # =========================================================
    # update_work_item_priority.py
    # =========================================================

    def test_update_work_item_priority_persists_priority(self) -> None:
        item = self._create_test_work_item("priority")

        self._invoke(
            update_work_item_priority,
            required=("work_item_id", "priority", "expected_updated_at"),
            work_item_id=item["id"],
            priority="critical",
            expected_updated_at=item["updated_at"],
        )

        stored = self._fetch_work_item(item["id"])

        self.assertIsNotNone(stored)
        assert stored is not None
        self.assertEqual(stored["priority"], "critical")

    def test_stale_priority_update_does_not_change_priority(
        self,
    ) -> None:
        item = self._create_test_work_item("stale-priority")

        self._invoke(
            update_work_item_priority,
            required=("work_item_id", "priority", "expected_updated_at"),
            work_item_id=item["id"],
            priority="critical",
            expected_updated_at=datetime(
                2000, 1, 1, tzinfo=timezone.utc
            ),
        )

        stored = self._fetch_work_item(item["id"])

        self.assertIsNotNone(stored)
        assert stored is not None
        self.assertEqual(stored["priority"], "medium")


if __name__ == "__main__":
    unittest.main(verbosity=2)