from __future__ import annotations

import inspect
import unittest
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from BACKEND.Postgres.gateway import get_connection

from BACKEND.Postgres.Operations.idempotency import errors as idempotency_errors
from BACKEND.Postgres.Operations.idempotency.reserve_idempotency_key import (
    reserve_idempotency_key,
)
from BACKEND.Postgres.Operations.idempotency.get_idempotency_record import (
    get_idempotency_record,
)
from BACKEND.Postgres.Operations.idempotency.complete_idempotency_record import (
    complete_idempotency_record,
)
from BACKEND.Postgres.Operations.idempotency.delete_expired_idempotency_records import (
    delete_expired_idempotency_records,
)


class IdempotencyOperationsIntegrationTests(unittest.TestCase):
    """
    PostgreSQL integration tests for idempotency operations.

    These tests use the configured PostgreSQL database and real operations.
    Test users and their idempotency records are disposable.

    Run:
        python -m BACKEND.Postgres.Operations.idempotency.test
    """

    # All test-owned user IDs are removed in tearDown().
    # Deleting users cascades to idempotency_records according to the schema.

    def setUp(self) -> None:
        self.marker = uuid4().hex
        self.created_user_ids: list[UUID | str] = []

        self.user_id = self._create_test_user("primary")
        self.other_user_id = self._create_test_user("secondary")

        self.valid_hash = "a" * 64
        self.other_hash = "b" * 64

    def tearDown(self) -> None:
        """
        Remove users created by this test.

        The idempotency_records.user_id foreign key is configured with
        ON DELETE CASCADE, so related records are removed automatically.
        """
        if not self.created_user_ids:
            return

        try:
            with get_connection() as connection:
                for user_id in reversed(self.created_user_ids):
                    connection.execute(
                        """
                        DELETE FROM users
                        WHERE id = %s
                        """,
                        (user_id,),
                    )
        except Exception as exc:
            # Do not conceal a test failure if cleanup is the underlying
            # problem, but emit enough information to diagnose it.
            print(
                "WARNING: Could not clean up all idempotency test users: "
                f"{type(exc).__name__}: {exc}"
            )

    # ============================================================
    # DATABASE AND FIXTURE HELPERS
    # ============================================================

    @staticmethod
    def _row_value(row, name: str, index: int = 0):
        """Read a value from a dict-like or tuple-like database row."""
        if row is None:
            return None

        if isinstance(row, dict):
            return row.get(name)

        try:
            return row[name]
        except (TypeError, KeyError, IndexError):
            try:
                return row[index]
            except (TypeError, KeyError, IndexError):
                return None

    def _create_test_user(self, suffix: str) -> UUID | str:
        """
        Create a minimal user directly in PostgreSQL.

        Account status uses the database default ('active').
        """
        full_name = f"Idempotency Test {suffix} {self.marker[:8]}"
        email = (
            f"idempotency-{suffix}-{self.marker}@example.test"
        )
        password_hash = "test-only-password-hash"

        with get_connection() as connection:
            cursor = connection.execute(
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
                    full_name,
                    email,
                    password_hash,
                ),
            )
            row = cursor.fetchone()

        user_id = self._row_value(row, "id", 0)

        if user_id is None:
            raise AssertionError(
                "Creating a test user did not return its ID."
            )

        self.created_user_ids.append(user_id)
        return user_id

    @staticmethod
    def _parameter_aliases() -> dict[str, tuple[str, ...]]:
        """
        Alias names let the test helper adapt to equivalent parameter names
        without passing unsupported keyword arguments to an operation.
        """
        return {
            "user_id": ("user_id", "owner_id"),
            "idempotency_key": ("idempotency_key", "key"),
            "request_hash": (
                "request_hash",
                "payload_hash",
                "request_digest",
            ),
            "expires_at": (
                "expires_at",
                "expiry",
                "expiration",
            ),
            "response_status": (
                "response_status",
                "status_code",
                "http_status",
            ),
            "response_body": (
                "response_body",
                "body",
                "response",
            ),
            "batch_size": (
                "batch_size",
                "batch_limit",
                "max_records",
                "limit",
            ),
            "connection": ("connection",),
        }

    def _invoke(self, operation, values: dict):
        """
        Call an operation with supported arguments only.

        This validates that every required parameter is supplied and gives
        a clear test failure if an operation signature changes.
        """
        signature = inspect.signature(operation)
        parameters = signature.parameters
        aliases = self._parameter_aliases()

        kwargs = {}

        for canonical_name, value in values.items():
            candidates = aliases.get(
                canonical_name,
                (canonical_name,),
            )

            for candidate in candidates:
                if candidate in parameters:
                    kwargs[candidate] = value
                    break

        missing = []

        for parameter_name, parameter in parameters.items():
            if parameter_name in kwargs:
                continue

            if parameter.kind in (
                inspect.Parameter.VAR_POSITIONAL,
                inspect.Parameter.VAR_KEYWORD,
            ):
                continue

            if parameter.default is inspect.Parameter.empty:
                missing.append(parameter_name)

        if missing:
            raise AssertionError(
                f"Missing required parameters for "
                f"{operation.__name__}: {missing}. "
                f"Actual parameters: {list(parameters)}. "
                f"Provided values: {list(values)}."
            )

        return operation(**kwargs)

    @staticmethod
    def _new_key(prefix: str = "test") -> str:
        return f"{prefix}-{uuid4().hex}"

    @staticmethod
    def _future_expiry(minutes: int = 30) -> datetime:
        return datetime.now(timezone.utc) + timedelta(
            minutes=minutes
        )

    def _reserve(
        self,
        *,
        user_id=None,
        key: str | None = None,
        request_hash: str | None = None,
        expires_at: datetime | None = None,
        connection=None,
    ):
        if user_id is None:
            user_id = self.user_id

        if key is None:
            key = self._new_key()

        if request_hash is None:
            request_hash = self.valid_hash

        if expires_at is None:
            expires_at = self._future_expiry()

        return self._invoke(
            reserve_idempotency_key,
            {
                "user_id": user_id,
                "idempotency_key": key,
                "request_hash": request_hash,
                "expires_at": expires_at,
                "connection": connection,
            },
        )

    def _get(
        self,
        *,
        user_id=None,
        key: str,
        connection=None,
    ):
        if user_id is None:
            user_id = self.user_id

        return self._invoke(
            get_idempotency_record,
            {
                "user_id": user_id,
                "idempotency_key": key,
                "connection": connection,
            },
        )

    def _complete(
        self,
        *,
        user_id=None,
        key: str,
        request_hash: str,
        response_status: int = 200,
        response_body=None,
        connection=None,
    ):
        """
        Mark a matching reservation as complete.

        IMPORTANT:
        complete_idempotency_record() identifies the reservation using
        user_id + idempotency_key + request_hash. It does not require a
        record_id. The request_hash must be the same hash used to reserve
        the key.
        """
        if user_id is None:
            user_id = self.user_id

        if response_body is None:
            response_body = {"success": True}

        return self._invoke(
            complete_idempotency_record,
            {
                "user_id": user_id,
                "idempotency_key": key,
                "request_hash": request_hash,
                "response_status": response_status,
                "response_body": response_body,
                "connection": connection,
            },
        )

    @staticmethod
    def _state_from_result(result):
        """
        Extract the reservation state from supported return shapes.

        Expected domain states:
            reserved
            in_progress
            replay
        """
        if result is None:
            return None

        if isinstance(result, str):
            normalized = result.strip().lower()
            if normalized in {
                "reserved",
                "in_progress",
                "replay",
            }:
                return normalized

        if isinstance(result, dict):
            for field in (
                "state",
                "reservation_state",
                "reservation_status",
            ):
                value = result.get(field)

                if isinstance(value, str):
                    normalized = value.strip().lower()
                    if normalized in {
                        "reserved",
                        "in_progress",
                        "replay",
                    }:
                        return normalized

            # Some implementations represent a completed replay through
            # its stored response rather than an explicit state.
            if (
                result.get("response_status") is not None
                and result.get("response_body") is not None
            ):
                return "replay"

        if isinstance(result, tuple):
            for item in result:
                state = IdempotencyOperationsIntegrationTests._state_from_result(
                    item
                )
                if state is not None:
                    return state

        return None

    @staticmethod
    def _record_field(record, name: str, fallback_index: int | None = None):
        if record is None:
            return None

        if isinstance(record, dict):
            return record.get(name)

        try:
            return record[name]
        except (TypeError, KeyError, IndexError):
            if fallback_index is None:
                return None

            try:
                return record[fallback_index]
            except (TypeError, KeyError, IndexError):
                return None

    def _set_record_expired(self, key: str) -> None:
        """
        Mark a record expired without violating the table's check constraint.

        The schema requires expires_at > created_at, so both timestamps are
        moved into the past.
        """
        old_created_at = datetime(2000, 1, 1, tzinfo=timezone.utc)
        old_expires_at = datetime(2000, 1, 2, tzinfo=timezone.utc)

        with get_connection() as connection:
            cursor = connection.execute(
                """
                UPDATE idempotency_records
                SET created_at = %s,
                    expires_at = %s
                WHERE user_id = %s
                  AND idempotency_key = %s
                RETURNING id
                """,
                (
                    old_created_at,
                    old_expires_at,
                    self.user_id,
                    key,
                ),
            )

            if cursor.fetchone() is None:
                raise AssertionError(
                    "Could not find the idempotency record to expire."
                )

    # ============================================================
    # ERROR DEFINITIONS
    # ============================================================

    def test_idempotency_errors_module_exposes_domain_exceptions(self):
        expected_errors = (
            "InvalidIdempotencyRecordError",
            "IdempotencyKeyReuseError",
            "IdempotencyRecordNotFoundError",
            "IdempotencyRecordExpiredError",
            "IdempotencyAlreadyCompletedError",
            "IdempotencyDatabaseError",
        )

        for error_name in expected_errors:
            with self.subTest(error=error_name):
                self.assertTrue(
                    hasattr(idempotency_errors, error_name),
                    f"Missing exception: {error_name}",
                )

                error_type = getattr(
                    idempotency_errors,
                    error_name,
                )
                self.assertTrue(
                    isinstance(error_type, type),
                    f"{error_name} is not an exception class.",
                )
                self.assertTrue(
                    issubclass(error_type, Exception),
                    f"{error_name} must inherit from Exception.",
                )

    # ============================================================
    # RESERVATION
    # ============================================================

    def test_reserve_idempotency_key_persists_new_reservation(self):
        key = self._new_key("new-reservation")

        result = self._reserve(
            key=key,
            request_hash=self.valid_hash,
        )

        state = self._state_from_result(result)

        if state is not None:
            self.assertEqual(state, "reserved")

        record = self._get(key=key)

        self.assertIsNotNone(record)
        self.assertEqual(
            str(self._record_field(record, "user_id", 1)),
            str(self.user_id),
        )
        self.assertEqual(
            self._record_field(record, "idempotency_key", 2),
            key,
        )
        self.assertEqual(
            self._record_field(record, "request_hash", 3),
            self.valid_hash,
        )
        self.assertIsNone(
            self._record_field(record, "response_status", 4)
        )
        self.assertIsNone(
            self._record_field(record, "response_body", 5)
        )

    def test_same_key_and_hash_is_reported_as_in_progress(self):
        key = self._new_key("in-progress")

        first_result = self._reserve(
            key=key,
            request_hash=self.valid_hash,
        )

        first_state = self._state_from_result(first_result)
        if first_state is not None:
            self.assertEqual(first_state, "reserved")

        second_result = self._reserve(
            key=key,
            request_hash=self.valid_hash,
        )

        self.assertEqual(
            self._state_from_result(second_result),
            "in_progress",
        )

    def test_reusing_key_with_different_hash_is_rejected(self):
        key = self._new_key("different-hash")

        self._reserve(
            key=key,
            request_hash=self.valid_hash,
        )

        with self.assertRaises(
            idempotency_errors.IdempotencyKeyReuseError
        ):
            self._reserve(
                key=key,
                request_hash=self.other_hash,
            )

    def test_same_key_is_scoped_independently_per_user(self):
        key = self._new_key("per-user")

        first_result = self._reserve(
            user_id=self.user_id,
            key=key,
            request_hash=self.valid_hash,
        )
        second_result = self._reserve(
            user_id=self.other_user_id,
            key=key,
            request_hash=self.valid_hash,
        )

        first_state = self._state_from_result(first_result)
        second_state = self._state_from_result(second_result)

        if first_state is not None:
            self.assertEqual(first_state, "reserved")

        if second_state is not None:
            self.assertEqual(second_state, "reserved")

        first_record = self._get(
            user_id=self.user_id,
            key=key,
        )
        second_record = self._get(
            user_id=self.other_user_id,
            key=key,
        )

        self.assertIsNotNone(first_record)
        self.assertIsNotNone(second_record)

        self.assertEqual(
            str(self._record_field(first_record, "user_id", 1)),
            str(self.user_id),
        )
        self.assertEqual(
            str(self._record_field(second_record, "user_id", 1)),
            str(self.other_user_id),
        )

    def test_reserve_rejects_invalid_request_hash(self):
        key = self._new_key("invalid-hash")

        invalid_hashes = (
            "",
            "not-a-hash",
            "a" * 63,
            "A" * 64,
            "g" * 64,
        )

        for invalid_hash in invalid_hashes:
            with self.subTest(request_hash=repr(invalid_hash)):
                with self.assertRaises(
                    idempotency_errors.InvalidIdempotencyRecordError
                ):
                    self._reserve(
                        key=self._new_key("invalid"),
                        request_hash=invalid_hash,
                    )

    def test_reserve_rejects_nonexistent_user(self):
        nonexistent_user_id = uuid4()

        with self.assertRaises(
            idempotency_errors.IdempotencyDatabaseError
        ):
            self._reserve(
                user_id=nonexistent_user_id,
                key=self._new_key("missing-user"),
                request_hash=self.valid_hash,
            )

    # ============================================================
    # READ
    # ============================================================

    def test_get_idempotency_record_returns_existing_record(self):
        key = self._new_key("get-existing")

        self._reserve(
            key=key,
            request_hash=self.valid_hash,
        )

        record = self._get(key=key)

        self.assertIsNotNone(record)
        self.assertEqual(
            self._record_field(record, "idempotency_key", 2),
            key,
        )
        self.assertEqual(
            self._record_field(record, "request_hash", 3),
            self.valid_hash,
        )

    def test_get_idempotency_record_returns_none_when_missing(self):
        record = self._get(
            key=self._new_key("missing-record"),
        )

        self.assertIsNone(record)

    # ============================================================
    # COMPLETION AND REPLAY
    # ============================================================

    def test_complete_idempotency_record_persists_response(self):
        key = self._new_key("complete")
        response_body = {
            "success": True,
            "work_item_id": "test-work-item-001",
            "message": "Operation completed",
        }

        self._reserve(
            key=key,
            request_hash=self.valid_hash,
        )

        # FIX: complete_idempotency_record requires request_hash.
        # Use the same hash that was used to reserve the key.
        self._complete(
            key=key,
            request_hash=self.valid_hash,
            response_status=201,
            response_body=response_body,
        )

        record = self._get(key=key)

        self.assertIsNotNone(record)
        self.assertEqual(
            self._record_field(record, "request_hash", 3),
            self.valid_hash,
        )
        self.assertEqual(
            self._record_field(record, "response_status", 4),
            201,
        )
        self.assertEqual(
            self._record_field(record, "response_body", 5),
            response_body,
        )

    def test_completed_request_is_returned_as_replay(self):
        key = self._new_key("replay")
        response_body = {
            "success": True,
            "result": {"id": "stable-result-001"},
        }

        self._reserve(
            key=key,
            request_hash=self.valid_hash,
        )

        # FIX: completion must use the original reservation's request hash.
        self._complete(
            key=key,
            request_hash=self.valid_hash,
            response_status=200,
            response_body=response_body,
        )

        replay_result = self._reserve(
            key=key,
            request_hash=self.valid_hash,
        )

        self.assertEqual(
            self._state_from_result(replay_result),
            "replay",
        )

        stored_record = self._get(key=key)

        self.assertIsNotNone(stored_record)
        self.assertEqual(
            self._record_field(stored_record, "response_status", 4),
            200,
        )
        self.assertEqual(
            self._record_field(stored_record, "response_body", 5),
            response_body,
        )

    # ============================================================
    # EXPIRY CLEANUP
    # ============================================================

    def test_delete_expired_idempotency_records_removes_expired_row(self):
        expired_key = self._new_key("expired")
        active_key = self._new_key("active")

        self._reserve(
            key=expired_key,
            request_hash=self.valid_hash,
        )

        self._reserve(
            key=active_key,
            request_hash=self.other_hash,
            expires_at=self._future_expiry(minutes=60),
        )

        # Set the expiry into the past after insertion so that the table's
        # expires_at > created_at check constraint remains valid.
        self._set_record_expired(expired_key)

        self._invoke(
            delete_expired_idempotency_records,
            {
                "batch_size": 100,
            },
        )

        expired_record = self._get(key=expired_key)
        active_record = self._get(key=active_key)

        self.assertIsNone(expired_record)
        self.assertIsNotNone(active_record)

    # ============================================================
    # TRANSACTION OWNERSHIP
    # ============================================================

    def test_reserve_idempotency_key_respects_caller_owned_transaction(self):
        key = self._new_key("rollback")

        # The caller owns this transaction. If it rolls back, the reservation
        # must not remain committed by the operation.
        with self.assertRaises(RuntimeError):
            with get_connection() as connection:
                self._reserve(
                    key=key,
                    request_hash=self.valid_hash,
                    connection=connection,
                )

                raise RuntimeError(
                    "Force rollback to verify transaction ownership."
                )

        record = self._get(key=key)
        self.assertIsNone(record)


if __name__ == "__main__":
    unittest.main(verbosity=2)