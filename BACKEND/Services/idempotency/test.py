"""Unit tests for the centralized idempotency Service."""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch
from uuid import uuid4

from BACKEND.Postgres.Operations.idempotency.errors import (
    IdempotencyKeyReuseError,
)
from BACKEND.Services.contracts import (
    ServiceResponse,
    service_failure,
    service_success,
)
from BACKEND.Services.idempotency import service as idempotency_service


class _FakeConnectionContext:
    """Record transaction exit behavior without a live database."""

    def __init__(self):
        self.connection = object()
        self.exception_type = None

    def __enter__(self):
        return self.connection

    def __exit__(self, exc_type, exc_value, traceback):
        self.exception_type = exc_type
        return False


class IdempotencyServiceTests(unittest.TestCase):

    def setUp(self):
        self.user_id = uuid4()
        self.connection_context = _FakeConnectionContext()
        self.environ_patch = patch.dict(
            os.environ,
            {"IDEMPOTENCY_HASH_SECRET": "test-secret-" + ("x" * 40)},
        )
        self.environ_patch.start()
        self.addCleanup(self.environ_patch.stop)

    def successful_response(self):
        return service_success(
            name="test_operation",
            category="test",
            subcategory="idempotency",
            description="Test operation.",
            data={"id": str(uuid4())},
            http_status=201,
        )

    def failed_response(self):
        return service_failure(
            name="test_operation",
            category="test",
            subcategory="idempotency",
            description="Test operation.",
            code="TEST_FAILURE",
            message="The operation failed.",
            http_status=400,
        )

    def call_service(
        self,
        *,
        key="test-idempotency-key",
        payload=None,
        operation=None,
    ):
        return idempotency_service.execute_idempotently(
            user_id=self.user_id,
            idempotency_key=key,
            operation_name="test_operation",
            category="test",
            subcategory="idempotency",
            description="Test operation.",
            payload=(
                {"value": "example"}
                if payload is None
                else payload
            ),
            operation=operation or (
                lambda connection: self.successful_response()
            ),
        )

    def test_hash_is_stable_for_different_dictionary_order(self):
        first = idempotency_service.hash_request(
            "test_operation",
            {"a": 1, "b": 2},
        )
        second = idempotency_service.hash_request(
            "test_operation",
            {"b": 2, "a": 1},
        )

        self.assertEqual(first, second)
        self.assertEqual(len(first), 64)

    def test_hash_changes_when_payload_changes(self):
        first = idempotency_service.hash_request(
            "test_operation",
            {"value": "one"},
        )
        second = idempotency_service.hash_request(
            "test_operation",
            {"value": "two"},
        )

        self.assertNotEqual(first, second)

    def test_hash_changes_when_operation_name_changes(self):
        first = idempotency_service.hash_request(
            "create_item",
            {"value": "same"},
        )
        second = idempotency_service.hash_request(
            "update_item",
            {"value": "same"},
        )

        self.assertNotEqual(first, second)

    def test_successful_request_saves_response(self):
        response = self.successful_response()
        completed = {}

        with (
            patch.object(
                idempotency_service,
                "get_connection",
                return_value=self.connection_context,
            ),
            patch.object(
                idempotency_service,
                "reserve_idempotency_key",
                return_value={"state": "reserved", "record": {}},
            ) as reserve,
            patch.object(
                idempotency_service,
                "complete_idempotency_record",
                side_effect=lambda **kwargs: completed.update(kwargs) or {},
            ),
        ):
            result = self.call_service(
                operation=lambda connection: response
            )

        self.assertIsInstance(result, ServiceResponse)
        self.assertTrue(result.success)
        self.assertEqual(result.http_status, 201)

        reserve.assert_called_once()
        self.assertIs(
            completed["connection"],
            self.connection_context.connection,
        )
        self.assertEqual(completed["user_id"], self.user_id)
        self.assertEqual(completed["response_status"], 201)
        self.assertTrue(completed["response_body"]["success"])
        self.assertIsNone(self.connection_context.exception_type)

    def test_completed_duplicate_replays_saved_response(self):
        saved_response = self.successful_response()
        operation_called = False

        def operation(connection):
            nonlocal operation_called
            operation_called = True
            return self.successful_response()

        with (
            patch.object(
                idempotency_service,
                "get_connection",
                return_value=self.connection_context,
            ),
            patch.object(
                idempotency_service,
                "reserve_idempotency_key",
                return_value={
                    "state": "replay",
                    "record": {
                        "response_body": saved_response.model_dump(
                            mode="json"
                        ),
                    },
                },
            ),
            patch.object(
                idempotency_service,
                "complete_idempotency_record",
            ) as complete,
        ):
            result = self.call_service(operation=operation)

        self.assertTrue(result.success)
        self.assertEqual(result.request_id, saved_response.request_id)
        self.assertFalse(operation_called)
        complete.assert_not_called()

    def test_reusing_key_with_different_payload_returns_conflict(self):
        with (
            patch.object(
                idempotency_service,
                "get_connection",
                return_value=self.connection_context,
            ),
            patch.object(
                idempotency_service,
                "reserve_idempotency_key",
                side_effect=IdempotencyKeyReuseError(
                    "Key belongs to a different request."
                ),
            ),
        ):
            result = self.call_service()

        self.assertFalse(result.success)
        self.assertEqual(result.http_status, 409)
        self.assertEqual(
            result.error.code,
            "IDEMPOTENCY_KEY_REUSED",
        )

    def test_in_progress_request_is_not_executed(self):
        operation_called = False

        def operation(connection):
            nonlocal operation_called
            operation_called = True
            return self.successful_response()

        with (
            patch.object(
                idempotency_service,
                "get_connection",
                return_value=self.connection_context,
            ),
            patch.object(
                idempotency_service,
                "reserve_idempotency_key",
                return_value={
                    "state": "in_progress",
                    "record": {},
                },
            ),
            patch.object(
                idempotency_service,
                "complete_idempotency_record",
            ) as complete,
        ):
            result = self.call_service(operation=operation)

        self.assertFalse(result.success)
        self.assertEqual(result.http_status, 409)
        self.assertEqual(
            result.error.code,
            "IDEMPOTENCY_IN_PROGRESS",
        )
        self.assertTrue(result.error.retryable)
        self.assertFalse(operation_called)
        complete.assert_not_called()
        self.assertIsNotNone(self.connection_context.exception_type)

    def test_failed_operation_rolls_back_and_is_not_cached(self):
        with (
            patch.object(
                idempotency_service,
                "get_connection",
                return_value=self.connection_context,
            ),
            patch.object(
                idempotency_service,
                "reserve_idempotency_key",
                return_value={"state": "reserved", "record": {}},
            ),
            patch.object(
                idempotency_service,
                "complete_idempotency_record",
            ) as complete,
        ):
            result = self.call_service(
                operation=lambda connection: self.failed_response()
            )

        self.assertFalse(result.success)
        self.assertEqual(result.error.code, "TEST_FAILURE")
        complete.assert_not_called()
        self.assertIsNotNone(self.connection_context.exception_type)

    def test_request_without_key_does_not_reserve_record(self):
        response = self.successful_response()

        with (
            patch.object(
                idempotency_service,
                "get_connection",
                return_value=self.connection_context,
            ),
            patch.object(
                idempotency_service,
                "reserve_idempotency_key",
            ) as reserve,
            patch.object(
                idempotency_service,
                "complete_idempotency_record",
            ) as complete,
        ):
            result = self.call_service(
                key=None,
                operation=lambda connection: response,
            )

        self.assertIs(result, response)
        reserve.assert_not_called()
        complete.assert_not_called()

    def test_invalid_key_is_rejected_before_database_access(self):
        with patch.object(
            idempotency_service,
            "get_connection",
        ) as get_connection:
            result = self.call_service(key="")

        self.assertFalse(result.success)
        self.assertEqual(result.http_status, 400)
        self.assertEqual(
            result.error.code,
            "INVALID_IDEMPOTENCY_KEY",
        )
        get_connection.assert_not_called()


if __name__ == "__main__":
    unittest.main()