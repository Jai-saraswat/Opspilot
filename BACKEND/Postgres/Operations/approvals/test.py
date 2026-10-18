"""PostgreSQL integration tests for OpsPilot approval Operations.

Run from the project root:
    python -m BACKEND.Postgres.Operations.approvals.test

Use a development/test database, never production.
"""

from __future__ import annotations

import inspect
import unittest
from typing import Any
from uuid import UUID, uuid4

from psycopg.rows import dict_row

from BACKEND.Postgres.gateway import get_connection
from BACKEND.Postgres.Operations.approvals import errors as approval_errors

from BACKEND.Postgres.Operations.approvals.create_approval_request import (
    create_approval_request,
)
from BACKEND.Postgres.Operations.approvals.get_approval_request_by_id import (
    get_approval_request_by_id,
)
from BACKEND.Postgres.Operations.approvals.list_pending_approvals import (
    list_pending_approvals,
)
from BACKEND.Postgres.Operations.approvals.list_work_item_approvals import (
    list_work_item_approvals,
)
from BACKEND.Postgres.Operations.approvals.list_user_approval_requests import (
    list_user_approval_requests,
)
from BACKEND.Postgres.Operations.approvals.assign_approval_approver import (
    assign_approval_approver,
)
from BACKEND.Postgres.Operations.approvals.record_approval_decision_if_pending import (
    record_approval_decision_if_pending,
)


class RollbackProbe(Exception):
    """Force a caller-owned transaction to roll back."""


class ApprovalsOperationsIntegrationTests(unittest.TestCase):
    """Test approval persistence and conditional decisions in PostgreSQL."""

    ARGUMENT_ALIASES = {
        "approval_request_id": (
            "approval_request_id",
            "request_id",
            "approval_id",
            "id",
        ),
        "work_item_id": ("work_item_id", "item_id"),
        "requested_by": (
            "requested_by",
            "requester_id",
            "created_by",
            "user_id",
        ),
        "approver_id": (
            "approver_id",
            "new_approver_id",
            "assigned_approver_id",
        ),
        "status": ("status", "decision", "new_status"),
        "decision_reason": ("decision_reason", "reason"),
        "limit": ("limit", "page_size"),
        "offset": ("offset",),
        "connection": ("connection",),
    }

    @classmethod
    def setUpClass(cls) -> None:
        """Check PostgreSQL connectivity and required tables."""
        required_tables = (
            "users",
            "teams",
            "work_items",
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
                        "Unable to determine PostgreSQL database."
                    )

                cls.database_name = row["database_name"]

                if any(
                    marker in cls.database_name.lower()
                    for marker in ("prod", "production", "live")
                ):
                    raise RuntimeError(
                        "Refusing to run integration tests against a "
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
                            f"Required table public.{table_name} is missing."
                        )

        print(
            f"\nConnected to PostgreSQL database: {cls.database_name}"
        )

    def setUp(self) -> None:
        """Create disposable users, team, and work item in dependency order."""
        self.marker = uuid4().hex
        self.created_user_ids: list[UUID] = []
        self.created_team_ids: list[UUID] = []

        # Create users first because the team requires a creator.
        self.user_a = self._create_test_user("requester")
        self.user_b = self._create_test_user("approver")

        # The team requires user_a.
        self.team_id = self._create_test_team()

        # The work item requires both the team and creator.
        self.work_item_id = self._create_test_work_item()

    def tearDown(self) -> None:
        """Remove only test-owned approval requests and fixtures."""
        with get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    DELETE FROM work_item_approval_requests
                    WHERE work_item_id = %s;
                    """,
                    (self.work_item_id,),
                )

                cursor.execute(
                    "DELETE FROM work_items WHERE id = %s;",
                    (self.work_item_id,),
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
        """Call an operation using its actual parameter names.

        Known parameter aliases accommodate naming differences. Required
        semantic arguments must be supported by the operation.
        """
        parameters = inspect.signature(operation).parameters
        kwargs: dict[str, Any] = {}
        matched: set[str] = set()

        for semantic_name, value in values.items():
            aliases = self.ARGUMENT_ALIASES.get(
                semantic_name,
                (semantic_name,),
            )

            target = next(
                (name for name in aliases if name in parameters),
                None,
            )

            if target is not None:
                kwargs[target] = value
                matched.add(semantic_name)

        missing = set(required) - matched

        if missing:
            raise AssertionError(
                f"{operation.__name__} does not expose required arguments "
                f"{sorted(missing)}. Actual parameters: "
                f"{list(parameters)}"
            )

        missing_parameters = [
            parameter.name
            for parameter in parameters.values()
            if parameter.kind in (
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
            if (
                "id" in result
                and "work_item_id" in result
                and "status" in result
            ):
                return [result]

            for key in (
                "approvals",
                "approval_requests",
                "items",
                "records",
                "results",
                "data",
            ):
                value = result.get(key)

                if isinstance(value, list):
                    if not all(isinstance(row, dict) for row in value):
                        raise AssertionError(
                            f"Invalid records under result key {key!r}."
                        )
                    return value

                if isinstance(value, dict):
                    return cls._extract_rows(value)

        raise AssertionError(
            "Unexpected list-operation result type: "
            f"{type(result).__name__}"
        )

    # =========================================================
    # FIXTURE HELPERS
    # =========================================================

    def _create_test_user(self, suffix: str) -> UUID:
        """Create a disposable test user."""
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
                        f"Approval Test {suffix} {self.marker}",
                        f"approval-{self.marker}-{suffix}@example.invalid",
                        f"test-only-hash-{uuid4().hex}",
                    ),
                )
                user_id = UUID(str(cursor.fetchone()[0]))

        self.created_user_ids.append(user_id)
        return user_id

    def _create_test_team(self) -> UUID:
        """Create a disposable team."""
        with get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO teams (name, description, created_by)
                    VALUES (%s, %s, %s)
                    RETURNING id;
                    """,
                    (
                        f"ApprovalTeam-{self.marker[:12]}",
                        "Approval integration-test team.",
                        self.user_a,
                    ),
                )
                team_id = UUID(str(cursor.fetchone()[0]))

        self.created_team_ids.append(team_id)
        return team_id

    def _create_test_work_item(self) -> UUID:
        """Create a disposable work item."""
        # setUp creates the requester first before recreating the real fixture.
        creator_id = (
            self.created_user_ids[0]
            if self.created_user_ids
            else self._create_test_user("bootstrap")
        )

        team_id = (
            self.created_team_ids[0]
            if self.created_team_ids
            else self._create_test_team()
        )

        with get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO work_items (
                        title,
                        description,
                        type,
                        status,
                        priority,
                        team_id,
                        created_by
                    )
                    VALUES (
                        %s,
                        %s,
                        'approval',
                        'open',
                        'medium',
                        %s,
                        %s
                    )
                    RETURNING id;
                    """,
                    (
                        f"ApprovalItem-{self.marker[:12]}-{uuid4().hex[:6]}",
                        f"Approval integration test {self.marker}",
                        team_id,
                        creator_id,
                    ),
                )
                return UUID(str(cursor.fetchone()[0]))

    def _delete_work_item(self, work_item_id: UUID) -> None:
        """Delete a setup-only work item before replacing the fixture."""
        with get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    DELETE FROM work_item_approval_requests
                    WHERE work_item_id = %s;
                    """,
                    (work_item_id,),
                )
                cursor.execute(
                    "DELETE FROM work_items WHERE id = %s;",
                    (work_item_id,),
                )

    def _fetch_approval(
        self,
        approval_request_id: UUID,
    ) -> dict[str, Any] | None:
        """Read the authoritative approval record from PostgreSQL."""
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
                    WHERE id = %s;
                    """,
                    (approval_request_id,),
                )
                row = cursor.fetchone()

        return dict(row) if row is not None else None

    def _create_test_approval_request(
        self,
        suffix: str = "request",
        *,
        approver_id: UUID | None = None,
        requested_by: UUID | None = None,
    ) -> dict[str, Any]:
        """Create an approval through the operation and read it from the DB."""
        requested_by = requested_by or self.user_a

        # Capture current IDs so the newly inserted record can be identified
        # even if the operation returns no ID or returns only selected fields.
        with get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id
                    FROM work_item_approval_requests
                    WHERE work_item_id = %s;
                    """,
                    (self.work_item_id,),
                )
                previous_ids = {
                    UUID(str(row[0]))
                    for row in cursor.fetchall()
                }

        self._invoke(
            create_approval_request,
            required=("work_item_id", "requested_by"),
            work_item_id=self.work_item_id,
            requested_by=requested_by,
            approver_id=approver_id,
        )

        with get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id
                    FROM work_item_approval_requests
                    WHERE work_item_id = %s;
                    """,
                    (self.work_item_id,),
                )
                current_ids = {
                    UUID(str(row[0]))
                    for row in cursor.fetchall()
                }

        new_ids = current_ids - previous_ids

        if len(new_ids) != 1:
            raise AssertionError(
                "Expected create_approval_request to add exactly one record; "
                f"found {len(new_ids)} new records."
            )

        stored = self._fetch_approval(new_ids.pop())

        if stored is None:
            raise AssertionError(
                "The approval request could not be read after creation."
            )

        return stored

    # =========================================================
    # errors.py
    # =========================================================

    def test_approval_errors_module_exposes_domain_exceptions(
        self,
    ) -> None:
        for name in (
            "InvalidApprovalRecordError",
            "ApprovalRelatedRecordNotFoundError",
            "ApprovalDatabaseError",
        ):
            with self.subTest(exception=name):
                exception_type = getattr(approval_errors, name)
                self.assertTrue(issubclass(exception_type, Exception))

    # =========================================================
    # create_approval_request.py
    # =========================================================

    def test_create_approval_request_persists_pending_record(
        self,
    ) -> None:
        approval = self._create_test_approval_request(
            "pending",
            approver_id=self.user_b,
        )

        self.assertEqual(approval["work_item_id"], self.work_item_id)
        self.assertEqual(approval["requested_by"], self.user_a)
        self.assertEqual(approval["approver_id"], self.user_b)
        self.assertEqual(approval["status"], "pending")
        self.assertIsNone(approval["decision_reason"])
        self.assertIsNotNone(approval["requested_at"])
        self.assertIsNone(approval["decided_at"])

    def test_create_approval_request_can_start_unassigned(
        self,
    ) -> None:
        approval = self._create_test_approval_request(
            "unassigned",
            approver_id=None,
        )

        self.assertIsNone(approval["approver_id"])
        self.assertEqual(approval["status"], "pending")
        self.assertIsNone(approval["decided_at"])

    def test_create_approval_request_rejects_missing_work_item(
        self,
    ) -> None:
        with self.assertRaises(
            approval_errors.ApprovalRelatedRecordNotFoundError
        ):
            self._invoke(
                create_approval_request,
                required=("work_item_id", "requested_by"),
                work_item_id=uuid4(),
                requested_by=self.user_a,
                approver_id=self.user_b,
            )

    # =========================================================
    # get_approval_request_by_id.py
    # =========================================================

    def test_get_approval_request_by_id_returns_existing_request(
        self,
    ) -> None:
        approval = self._create_test_approval_request("get")

        result = self._invoke(
            get_approval_request_by_id,
            required=("approval_request_id",),
            approval_request_id=UUID(str(approval["id"])),
        )

        self.assertIsNotNone(result)
        self.assertEqual(str(result["id"]), str(approval["id"]))
        self.assertEqual(result["status"], "pending")

    def test_get_approval_request_by_id_returns_none_when_missing(
        self,
    ) -> None:
        result = self._invoke(
            get_approval_request_by_id,
            required=("approval_request_id",),
            approval_request_id=uuid4(),
        )

        self.assertIsNone(result)

    # =========================================================
    # list_pending_approvals.py
    # =========================================================

    def test_list_pending_approvals_includes_pending_request(
        self,
    ) -> None:
        approval = self._create_test_approval_request(
            "pending-list",
            approver_id=self.user_b,
        )

        rows = self._extract_rows(
            self._invoke(
                list_pending_approvals,
                limit=100,
                offset=0,
            )
        )

        returned_ids = {str(row["id"]) for row in rows}

        self.assertIn(str(approval["id"]), returned_ids)

        matching = [
            row
            for row in rows
            if str(row["id"]) == str(approval["id"])
        ]
        self.assertEqual(matching[0]["status"], "pending")

    # =========================================================
    # list_work_item_approvals.py
    # =========================================================

    def test_list_work_item_approvals_returns_requests_for_item(
        self,
    ) -> None:
        first = self._create_test_approval_request("item-a")
        second = self._create_test_approval_request("item-b")

        rows = self._extract_rows(
            self._invoke(
                list_work_item_approvals,
                required=("work_item_id",),
                work_item_id=self.work_item_id,
                limit=100,
                offset=0,
            )
        )

        returned_ids = {str(row["id"]) for row in rows}

        self.assertIn(str(first["id"]), returned_ids)
        self.assertIn(str(second["id"]), returned_ids)
        self.assertTrue(
            all(
                str(row["work_item_id"]) == str(self.work_item_id)
                for row in rows
            ),
            "The list included approvals for a different work item.",
        )

    # =========================================================
    # list_user_approval_requests.py
    # =========================================================

    def test_list_user_approval_requests_returns_requester_records(
        self,
    ) -> None:
        approval = self._create_test_approval_request(
            "user-list",
            requested_by=self.user_a,
        )

        rows = self._extract_rows(
            self._invoke(
                list_user_approval_requests,
                required=("requested_by",),
                requested_by=self.user_a,
                limit=100,
                offset=0,
            )
        )

        returned_ids = {str(row["id"]) for row in rows}
        self.assertIn(str(approval["id"]), returned_ids)

        self.assertTrue(
            all(
                str(row["requested_by"]) == str(self.user_a)
                for row in rows
            ),
            "The request list returned records for another requester.",
        )

    # =========================================================
    # assign_approval_approver.py
    # =========================================================

    def test_assign_approval_approver_sets_approver(
        self,
    ) -> None:
        approval = self._create_test_approval_request(
            "assign-approver",
            approver_id=None,
        )

        self._invoke(
            assign_approval_approver,
            required=("approval_request_id", "approver_id"),
            approval_request_id=UUID(str(approval["id"])),
            approver_id=self.user_b,
        )

        stored = self._fetch_approval(UUID(str(approval["id"])))

        self.assertIsNotNone(stored)
        assert stored is not None
        self.assertEqual(stored["approver_id"], self.user_b)
        self.assertEqual(stored["status"], "pending")

    # =========================================================
    # record_approval_decision_if_pending.py
    # =========================================================

    def test_record_approval_decision_marks_request_approved(
        self,
    ) -> None:
        approval = self._create_test_approval_request(
            "approve",
            approver_id=self.user_b,
        )

        self._invoke(
            record_approval_decision_if_pending,
            required=("approval_request_id", "status"),
            approval_request_id=UUID(str(approval["id"])),
            status="approved",
            decision_reason="Approved by integration test.",
        )

        stored = self._fetch_approval(UUID(str(approval["id"])))

        self.assertIsNotNone(stored)
        assert stored is not None

        self.assertEqual(stored["status"], "approved")
        self.assertEqual(
            stored["decision_reason"],
            "Approved by integration test.",
        )
        self.assertIsNotNone(stored["decided_at"])

    def test_record_approval_decision_marks_request_rejected(
        self,
    ) -> None:
        approval = self._create_test_approval_request(
            "reject",
            approver_id=self.user_b,
        )

        self._invoke(
            record_approval_decision_if_pending,
            required=("approval_request_id", "status"),
            approval_request_id=UUID(str(approval["id"])),
            status="rejected",
            decision_reason="Rejected by integration test.",
        )

        stored = self._fetch_approval(UUID(str(approval["id"])))

        self.assertIsNotNone(stored)
        assert stored is not None

        self.assertEqual(stored["status"], "rejected")
        self.assertEqual(
            stored["decision_reason"],
            "Rejected by integration test.",
        )
        self.assertIsNotNone(stored["decided_at"])

    def test_record_approval_decision_cannot_overwrite_decided_request(
        self,
    ) -> None:
        approval = self._create_test_approval_request(
            "no-overwrite",
            approver_id=self.user_b,
        )
        approval_id = UUID(str(approval["id"]))

        self._invoke(
            record_approval_decision_if_pending,
            required=("approval_request_id", "status"),
            approval_request_id=approval_id,
            status="approved",
            decision_reason="First decision.",
        )

        original = self._fetch_approval(approval_id)
        self.assertIsNotNone(original)
        assert original is not None

        # Depending on the operation contract, a repeated decision may return
        # no row or raise the domain error for a request no longer pending.
        try:
            self._invoke(
                record_approval_decision_if_pending,
                required=("approval_request_id", "status"),
                approval_request_id=approval_id,
                status="rejected",
                decision_reason="Attempted second decision.",
            )
        except approval_errors.ApprovalRelatedRecordNotFoundError:
            pass

        after_retry = self._fetch_approval(approval_id)

        self.assertIsNotNone(after_retry)
        assert after_retry is not None

        self.assertEqual(after_retry["status"], "approved")
        self.assertEqual(
            after_retry["decision_reason"],
            "First decision.",
        )
        self.assertEqual(
            after_retry["decided_at"],
            original["decided_at"],
        )

    # =========================================================
    # CALLER-OWNED TRANSACTION
    # =========================================================

    def test_create_approval_request_respects_caller_owned_transaction(
        self,
    ) -> None:
        with get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT COUNT(*)
                    FROM work_item_approval_requests
                    WHERE work_item_id = %s;
                    """,
                    (self.work_item_id,),
                )
                before_count = cursor.fetchone()[0]

        with self.assertRaises(RollbackProbe):
            with get_connection() as connection:
                self._invoke(
                    create_approval_request,
                    required=(
                        "work_item_id",
                        "requested_by",
                        "connection",
                    ),
                    work_item_id=self.work_item_id,
                    requested_by=self.user_a,
                    approver_id=self.user_b,
                    connection=connection,
                )

                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT COUNT(*)
                        FROM work_item_approval_requests
                        WHERE work_item_id = %s;
                        """,
                        (self.work_item_id,),
                    )
                    self.assertEqual(
                        cursor.fetchone()[0],
                        before_count + 1,
                    )

                raise RollbackProbe(
                    "Force caller-owned approval transaction rollback."
                )

        with get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT COUNT(*)
                    FROM work_item_approval_requests
                    WHERE work_item_id = %s;
                    """,
                    (self.work_item_id,),
                )
                self.assertEqual(
                    cursor.fetchone()[0],
                    before_count,
                    "create_approval_request committed a caller-owned transaction.",
                )


if __name__ == "__main__":
    unittest.main(verbosity=2)