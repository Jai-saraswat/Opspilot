"""PostgreSQL integration tests for OpsPilot authorization Operations.

Run from the project root:
    python -m BACKEND.Postgres.Operations.authorization.test

Use a development/test database, never production.
Tests create disposable users, teams, roles, and permissions.
"""

from __future__ import annotations

import inspect
import unittest
from typing import Any
from uuid import UUID, uuid4

from psycopg.rows import dict_row

from BACKEND.Postgres.gateway import get_connection
from BACKEND.Postgres.Operations.authorization import errors as auth_errors

from BACKEND.Postgres.Operations.authorization.create_role import create_role
from BACKEND.Postgres.Operations.authorization.get_role_by_id import (
    get_role_by_id,
)
from BACKEND.Postgres.Operations.authorization.get_role_by_name import (
    get_role_by_name,
)
from BACKEND.Postgres.Operations.authorization.list_roles import list_roles

from BACKEND.Postgres.Operations.authorization.get_permission_by_key import (
    get_permission_by_key,
)
from BACKEND.Postgres.Operations.authorization.list_permissions import (
    list_permissions,
)
from BACKEND.Postgres.Operations.authorization.list_role_permissions import (
    list_role_permissions,
)
from BACKEND.Postgres.Operations.authorization.list_user_roles import (
    list_user_roles,
)

from BACKEND.Postgres.Operations.authorization.assign_role_to_user import (
    assign_role_to_user,
)
from BACKEND.Postgres.Operations.authorization.remove_role_from_user import (
    remove_role_from_user,
)
from BACKEND.Postgres.Operations.authorization.add_permission_to_role import (
    add_permission_to_role,
)
from BACKEND.Postgres.Operations.authorization.remove_permission_from_role import (
    remove_permission_from_role,
)

from BACKEND.Postgres.Operations.authorization.set_user_permission_override import (
    set_user_permission_override,
)
from BACKEND.Postgres.Operations.authorization.get_user_permission_overrides import (
    get_user_permission_overrides,
)
from BACKEND.Postgres.Operations.authorization.remove_user_permission_overrides import (
    remove_user_permission_overrides as remove_user_permission_override,
)


class RollbackProbe(Exception):
    """Force a caller-owned transaction to roll back."""


class AuthorizationOperationsIntegrationTests(unittest.TestCase):
    """Exercise authorization persistence against PostgreSQL."""

    ARGUMENT_ALIASES = {
        "name": ("name", "role_name"),
        "scope": ("scope", "role_scope"),
        "description": ("description",),
        "is_system_role": ("is_system_role",),
        "role_id": ("role_id",),
        "permission_id": ("permission_id",),
        "permission_key": ("permission_key", "key"),
        "user_id": ("user_id",),
        "assigned_by": ("assigned_by", "granted_by", "actor_id"),
        "team_id": ("team_id", "scope_team_id"),
        "effect": ("effect",),
        "connection": ("connection",),
        "limit": ("limit", "page_size"),
        "offset": ("offset",),
        "search": ("search", "query"),
    }

    @classmethod
    def setUpClass(cls) -> None:
        """Check database connectivity and required tables."""
        required_tables = (
            "users",
            "teams",
            "roles",
            "permissions",
            "role_permissions",
            "user_roles",
            "user_permission_overrides",
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
        """Create isolated user/team fixtures for each test."""
        self.marker = uuid4().hex
        self.created_user_ids: list[UUID] = []
        self.created_team_ids: list[UUID] = []
        self.created_role_ids: list[UUID] = []
        self.created_permission_ids: list[UUID] = []

        self.user_a = self._create_test_user("alpha")
        self.user_b = self._create_test_user("beta")
        self.team_a = self._create_test_team()

    def tearDown(self) -> None:
        """Remove only test-owned records."""
        with get_connection() as connection:
            with connection.cursor() as cursor:
                # Team-scoped overrides cascade when their team is removed.
                for team_id in self.created_team_ids:
                    cursor.execute(
                        "DELETE FROM teams WHERE id = %s",
                        (team_id,),
                    )

                # Roles cascade to their role_permissions and user_roles rows.
                for role_id in self.created_role_ids:
                    cursor.execute(
                        "DELETE FROM roles WHERE id = %s",
                        (role_id,),
                    )

                # Permissions cascade to role links and permission overrides.
                for permission_id in self.created_permission_ids:
                    cursor.execute(
                        "DELETE FROM permissions WHERE id = %s",
                        (permission_id,),
                    )

                for user_id in self.created_user_ids:
                    cursor.execute(
                        "DELETE FROM users WHERE id = %s",
                        (user_id,),
                    )

    # =========================================================
    # INVOCATION AND RESULT HELPERS
    # =========================================================

    def _invoke(self, operation: Any, **values: Any) -> Any:
        """Invoke a keyword-only operation using recognized parameter names.

        Most Operations use keyword-only inputs. A small alias map allows
        equivalent names such as name/role_name without hiding missing
        required arguments or database failures.
        """
        signature = inspect.signature(operation)
        parameters = signature.parameters
        kwargs: dict[str, Any] = {}

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
                raise AssertionError(
                    f"{operation.__name__} does not expose a parameter "
                    f"for {semantic_name!r}. Actual parameters: "
                    f"{list(parameters)}"
                )

            kwargs[target_name] = value

        for parameter in parameters.values():
            if parameter.kind in (
                inspect.Parameter.VAR_POSITIONAL,
                inspect.Parameter.VAR_KEYWORD,
            ):
                continue

            if (
                parameter.default is inspect.Parameter.empty
                and parameter.name not in kwargs
            ):
                raise AssertionError(
                    f"Missing required parameter {parameter.name!r} "
                    f"for {operation.__name__}."
                )

        return operation(**kwargs)

    @classmethod
    def _extract_rows(cls, result: Any) -> list[dict[str, Any]]:
        """Normalize common list-operation results."""
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
                "user_id" in result
                and (
                    "id" in result
                    or "role_id" in result
                    or "permission_id" in result
                )
            ):
                return [result]

            for key in (
                "items",
                "roles",
                "permissions",
                "user_roles",
                "overrides",
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

    @staticmethod
    def _value(row: dict[str, Any], *keys: str) -> Any:
        """Get the first available equivalent identifier field."""
        for key in keys:
            if key in row:
                return row[key]

        raise AssertionError(
            f"Expected one of fields {keys}; got {list(row)}"
        )

    # =========================================================
    # DATABASE FIXTURES
    # =========================================================

    def _create_test_user(self, suffix: str) -> UUID:
        email = (
            f"auth-test-{self.marker}-{suffix}@example.invalid"
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
                        f"Authorization Test {suffix} {self.marker}",
                        email,
                        f"test-only-hash-{uuid4().hex}",
                    ),
                )
                user_id = UUID(str(cursor.fetchone()[0]))

        self.created_user_ids.append(user_id)
        return user_id

    def _create_test_team(self) -> UUID:
        name = f"AuthTestTeam-{self.marker}"

        with get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO teams (name, description, created_by)
                    VALUES (%s, %s, %s)
                    RETURNING id;
                    """,
                    (
                        name,
                        "Temporary authorization integration-test team.",
                        self.user_a,
                    ),
                )
                team_id = UUID(str(cursor.fetchone()[0]))

        self.created_team_ids.append(team_id)
        return team_id

    def _create_test_role(
        self,
        suffix: str = "role",
        *,
        scope: str = "system",
    ) -> dict[str, Any]:
        """Create a role through the role operation and track its row."""
        name = f"AuthRole-{self.marker[:10]}-{suffix}"

        self._invoke(
            create_role,
            name=name,
            scope=scope,
            description="Temporary authorization integration-test role.",
            is_system_role=False,
        )

        row = self._fetch_role_by_name(name, scope)

        if row is None:
            raise AssertionError(
                "create_role returned without persisting the role."
            )

        self.created_role_ids.append(UUID(str(row["id"])))
        return row

    def _create_test_permission(self, suffix: str = "permission") -> dict[str, Any]:
        """Insert a temporary catalogue permission for relationship tests."""
        permission_key = f"auth.test.{self.marker}.{suffix}"

        with get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO permissions (permission_key, description)
                    VALUES (%s, %s)
                    RETURNING id;
                    """,
                    (
                        permission_key,
                        "Temporary integration-test permission.",
                    ),
                )
                permission_id = UUID(str(cursor.fetchone()[0]))

        self.created_permission_ids.append(permission_id)

        row = self._fetch_permission_by_key(permission_key)

        if row is None:
            raise AssertionError(
                "The test permission could not be read back."
            )

        return row

    def _fetch_role_by_id(
        self,
        role_id: UUID,
    ) -> dict[str, Any] | None:
        with get_connection() as connection:
            with connection.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    """
                    SELECT id, name, scope, description, is_system_role,
                           created_at
                    FROM roles
                    WHERE id = %s;
                    """,
                    (role_id,),
                )
                row = cursor.fetchone()

        return dict(row) if row is not None else None

    def _fetch_role_by_name(
        self,
        name: str,
        scope: str,
    ) -> dict[str, Any] | None:
        with get_connection() as connection:
            with connection.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    """
                    SELECT id, name, scope, description, is_system_role,
                           created_at
                    FROM roles
                    WHERE name = %s AND scope = %s;
                    """,
                    (name, scope),
                )
                row = cursor.fetchone()

        return dict(row) if row is not None else None

    def _fetch_permission_by_key(
        self,
        permission_key: str,
    ) -> dict[str, Any] | None:
        with get_connection() as connection:
            with connection.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    """
                    SELECT id, permission_key, description
                    FROM permissions
                    WHERE permission_key = %s;
                    """,
                    (permission_key,),
                )
                row = cursor.fetchone()

        return dict(row) if row is not None else None

    def _fetch_role_permission_count(
        self,
        role_id: UUID,
        permission_id: UUID,
    ) -> int:
        with get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT COUNT(*)
                    FROM role_permissions
                    WHERE role_id = %s AND permission_id = %s;
                    """,
                    (role_id, permission_id),
                )
                return cursor.fetchone()[0]

    def _fetch_user_role_count(
        self,
        user_id: UUID,
        role_id: UUID,
    ) -> int:
        with get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT COUNT(*)
                    FROM user_roles
                    WHERE user_id = %s AND role_id = %s;
                    """,
                    (user_id, role_id),
                )
                return cursor.fetchone()[0]

    def _fetch_override(
        self,
        user_id: UUID,
        permission_id: UUID,
        team_id: UUID | None,
    ) -> dict[str, Any] | None:
        with get_connection() as connection:
            with connection.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    """
                    SELECT id, user_id, permission_id, team_id,
                           effect, assigned_by, created_at
                    FROM user_permission_overrides
                    WHERE user_id = %s
                      AND permission_id = %s
                      AND team_id IS NOT DISTINCT FROM %s;
                    """,
                    (user_id, permission_id, team_id),
                )
                row = cursor.fetchone()

        return dict(row) if row is not None else None

    def _fetch_override_count(
        self,
        user_id: UUID,
        permission_id: UUID,
    ) -> int:
        with get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT COUNT(*)
                    FROM user_permission_overrides
                    WHERE user_id = %s AND permission_id = %s;
                    """,
                    (user_id, permission_id),
                )
                return cursor.fetchone()[0]

    # =========================================================
    # errors.py
    # =========================================================

    def test_authorization_errors_module_exposes_domain_exceptions(
        self,
    ) -> None:
        for name in (
            "RoleAlreadyExistsError",
            "InvalidAuthorizationRecordError",
            "AuthorizationRelatedRecordNotFoundError",
            "AuthorizationDatabaseError",
        ):
            with self.subTest(exception=name):
                exception_type = getattr(auth_errors, name)
                self.assertTrue(issubclass(exception_type, Exception))

    # =========================================================
    # create_role.py
    # =========================================================

    def test_create_role_persists_role_metadata(self) -> None:
        role = self._create_test_role(
            "metadata",
            scope="system",
        )

        stored = self._fetch_role_by_id(UUID(str(role["id"])))

        self.assertIsNotNone(stored)
        assert stored is not None

        self.assertEqual(stored["name"], role["name"])
        self.assertEqual(stored["scope"], "system")
        self.assertEqual(
            stored["description"],
            "Temporary authorization integration-test role.",
        )
        self.assertIsNotNone(stored["created_at"])

    def test_create_role_rejects_duplicate_name_in_same_scope(
        self,
    ) -> None:
        role = self._create_test_role("duplicate", scope="system")

        with self.assertRaises(auth_errors.RoleAlreadyExistsError):
            self._invoke(
                create_role,
                name=role["name"],
                scope="system",
                description="Duplicate name should be rejected.",
                is_system_role=False,
            )

        with get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT COUNT(*)
                    FROM roles
                    WHERE name = %s AND scope = %s;
                    """,
                    (role["name"], "system"),
                )
                self.assertEqual(cursor.fetchone()[0], 1)

    def test_create_role_allows_same_name_in_different_scopes(
        self,
    ) -> None:
        name = f"AuthShared-{self.marker}"

        self._invoke(
            create_role,
            name=name,
            scope="system",
            description="System-scoped fixture.",
            is_system_role=False,
        )
        self._invoke(
            create_role,
            name=name,
            scope="team",
            description="Team-scoped fixture.",
            is_system_role=False,
        )

        system_role = self._fetch_role_by_name(name, "system")
        team_role = self._fetch_role_by_name(name, "team")

        self.assertIsNotNone(system_role)
        self.assertIsNotNone(team_role)
        assert system_role is not None
        assert team_role is not None

        self.created_role_ids.extend(
            [
                UUID(str(system_role["id"])),
                UUID(str(team_role["id"])),
            ]
        )

        self.assertNotEqual(system_role["id"], team_role["id"])

    def test_create_role_rejects_invalid_scope(self) -> None:
        with self.assertRaises(
            auth_errors.InvalidAuthorizationRecordError
        ):
            self._invoke(
                create_role,
                name=f"AuthInvalid-{self.marker}",
                scope="organization",
                description="Invalid scope test.",
                is_system_role=False,
            )

    # =========================================================
    # get_role_by_id.py / get_role_by_name.py
    # =========================================================

    def test_get_role_by_id_returns_existing_role(self) -> None:
        role = self._create_test_role("by-id")

        result = self._invoke(
            get_role_by_id,
            role_id=UUID(str(role["id"])),
        )

        self.assertIsNotNone(result)
        self.assertEqual(str(result["id"]), str(role["id"]))
        self.assertEqual(result["name"], role["name"])

    def test_get_role_by_id_returns_none_for_missing_role(self) -> None:
        self.assertIsNone(
            self._invoke(get_role_by_id, role_id=uuid4())
        )

    def test_get_role_by_name_returns_matching_scope(self) -> None:
        role = self._create_test_role(
            "by-name",
            scope="team",
        )

        result = self._invoke(
            get_role_by_name,
            name=role["name"],
            scope="team",
        )

        self.assertIsNotNone(result)
        self.assertEqual(result["name"], role["name"])
        self.assertEqual(result["scope"], "team")

    def test_get_role_by_name_returns_none_when_missing(self) -> None:
        result = self._invoke(
            get_role_by_name,
            name=f"missing-{self.marker}",
            scope="system",
        )

        self.assertIsNone(result)

    # =========================================================
    # list_roles.py
    # =========================================================

    def test_list_roles_filters_by_scope(self) -> None:
        system_role = self._create_test_role(
            "listed-system",
            scope="system",
        )
        team_role = self._create_test_role(
            "listed-team",
            scope="team",
        )

        rows = self._extract_rows(
            self._invoke(
                list_roles,
                scope="system",
            )
        )

        returned_ids = {
            str(self._value(row, "id", "role_id"))
            for row in rows
        }

        self.assertIn(str(system_role["id"]), returned_ids)
        self.assertNotIn(str(team_role["id"]), returned_ids)

        self.assertTrue(
            all(row["scope"] == "system" for row in rows),
            "The role list returned a role from another scope.",
        )

    # =========================================================
    # get_permission_by_key.py / list_permissions.py
    # =========================================================

    def test_get_permission_by_key_returns_matching_permission(
        self,
    ) -> None:
        permission = self._create_test_permission("by-key")

        result = self._invoke(
            get_permission_by_key,
            permission_key=permission["permission_key"],
        )

        self.assertIsNotNone(result)
        self.assertEqual(
            str(result["id"]),
            str(permission["id"]),
        )
        self.assertEqual(
            result["permission_key"],
            permission["permission_key"],
        )

    def test_get_permission_by_key_returns_none_when_missing(
        self,
    ) -> None:
        result = self._invoke(
            get_permission_by_key,
            permission_key=f"missing.{self.marker}",
        )

        self.assertIsNone(result)

    def test_list_permissions_includes_catalogue_permission(self) -> None:
        permission = self._create_test_permission("listed")

        rows = self._extract_rows(list_permissions())

        returned_keys = {
            row.get("permission_key")
            for row in rows
        }

        self.assertIn(
            permission["permission_key"],
            returned_keys,
        )

    # =========================================================
    # add_permission_to_role.py / remove_permission_from_role.py
    # =========================================================

    def test_add_permission_to_role_persists_relationship(self) -> None:
        role = self._create_test_role("permission-link")
        permission = self._create_test_permission("linked")

        self._invoke(
            add_permission_to_role,
            role_id=UUID(str(role["id"])),
            permission_id=UUID(str(permission["id"])),
        )

        self.assertEqual(
            self._fetch_role_permission_count(
                UUID(str(role["id"])),
                UUID(str(permission["id"])),
            ),
            1,
        )

    def test_add_permission_to_role_is_duplicate_safe(self) -> None:
        role = self._create_test_role("duplicate-permission-link")
        permission = self._create_test_permission("duplicate-linked")

        for _ in range(2):
            self._invoke(
                add_permission_to_role,
                role_id=UUID(str(role["id"])),
                permission_id=UUID(str(permission["id"])),
            )

        self.assertEqual(
            self._fetch_role_permission_count(
                UUID(str(role["id"])),
                UUID(str(permission["id"])),
            ),
            1,
        )

    def test_list_role_permissions_returns_attached_permission(
        self,
    ) -> None:
        role = self._create_test_role("list-permissions")
        permission = self._create_test_permission("listed-on-role")

        self._invoke(
            add_permission_to_role,
            role_id=UUID(str(role["id"])),
            permission_id=UUID(str(permission["id"])),
        )

        rows = self._extract_rows(
            self._invoke(
                list_role_permissions,
                role_id=UUID(str(role["id"])),
            )
        )

        returned_permission_ids = {
            str(self._value(row, "permission_id", "id"))
            for row in rows
        }

        self.assertIn(str(permission["id"]), returned_permission_ids)

    def test_remove_permission_from_role_removes_relationship(
        self,
    ) -> None:
        role = self._create_test_role("remove-permission")
        permission = self._create_test_permission("remove-linked")

        role_id = UUID(str(role["id"]))
        permission_id = UUID(str(permission["id"]))

        self._invoke(
            add_permission_to_role,
            role_id=role_id,
            permission_id=permission_id,
        )
        self.assertEqual(
            self._fetch_role_permission_count(role_id, permission_id),
            1,
        )

        self._invoke(
            remove_permission_from_role,
            role_id=role_id,
            permission_id=permission_id,
        )

        self.assertEqual(
            self._fetch_role_permission_count(role_id, permission_id),
            0,
        )

    # =========================================================
    # assign_role_to_user.py / remove_role_from_user.py
    # =========================================================

    def test_assign_role_to_user_persists_assignment(self) -> None:
        role = self._create_test_role("assign")
        role_id = UUID(str(role["id"]))

        self._invoke(
            assign_role_to_user,
            user_id=self.user_a,
            role_id=role_id,
            assigned_by=self.user_b,
        )

        self.assertEqual(
            self._fetch_user_role_count(self.user_a, role_id),
            1,
        )

    def test_assign_role_to_user_is_duplicate_safe(self) -> None:
        role = self._create_test_role("duplicate-assignment")
        role_id = UUID(str(role["id"]))

        for _ in range(2):
            self._invoke(
                assign_role_to_user,
                user_id=self.user_a,
                role_id=role_id,
                assigned_by=self.user_b,
            )

        self.assertEqual(
            self._fetch_user_role_count(self.user_a, role_id),
            1,
        )

    def test_list_user_roles_returns_assigned_role(self) -> None:
        role = self._create_test_role("list-user-roles")
        role_id = UUID(str(role["id"]))

        self._invoke(
            assign_role_to_user,
            user_id=self.user_a,
            role_id=role_id,
            assigned_by=self.user_b,
        )

        rows = self._extract_rows(
            self._invoke(
                list_user_roles,
                user_id=self.user_a,
            )
        )

        returned_role_ids = {
            str(self._value(row, "role_id", "id"))
            for row in rows
        }

        self.assertIn(str(role_id), returned_role_ids)

    def test_remove_role_from_user_removes_assignment(self) -> None:
        role = self._create_test_role("remove-user-role")
        role_id = UUID(str(role["id"]))

        self._invoke(
            assign_role_to_user,
            user_id=self.user_a,
            role_id=role_id,
            assigned_by=self.user_b,
        )

        self._invoke(
            remove_role_from_user,
            user_id=self.user_a,
            role_id=role_id,
        )

        self.assertEqual(
            self._fetch_user_role_count(self.user_a, role_id),
            0,
        )

    # =========================================================
    # set_user_permission_override.py
    # get_user_permission_overrides.py
    # remove_user_permission_override.py
    # =========================================================

    def test_set_user_permission_override_persists_global_allow(
        self,
    ) -> None:
        permission = self._create_test_permission("global-allow")
        permission_id = UUID(str(permission["id"]))

        self._invoke(
            set_user_permission_override,
            user_id=self.user_a,
            permission_id=permission_id,
            effect="allow",
            team_id=None,
            assigned_by=self.user_b,
        )

        stored = self._fetch_override(
            self.user_a,
            permission_id,
            None,
        )

        self.assertIsNotNone(stored)
        assert stored is not None

        self.assertEqual(stored["effect"], "allow")
        self.assertIsNone(stored["team_id"])
        self.assertEqual(stored["assigned_by"], self.user_b)

    def test_set_user_permission_override_updates_existing_effect(
        self,
    ) -> None:
        permission = self._create_test_permission("effect-update")
        permission_id = UUID(str(permission["id"]))

        self._invoke(
            set_user_permission_override,
            user_id=self.user_a,
            permission_id=permission_id,
            effect="allow",
            team_id=None,
            assigned_by=self.user_b,
        )

        original = self._fetch_override(
            self.user_a,
            permission_id,
            None,
        )
        self.assertIsNotNone(original)

        self._invoke(
            set_user_permission_override,
            user_id=self.user_a,
            permission_id=permission_id,
            effect="deny",
            team_id=None,
            assigned_by=self.user_b,
        )

        updated = self._fetch_override(
            self.user_a,
            permission_id,
            None,
        )

        self.assertIsNotNone(updated)
        assert updated is not None
        assert original is not None

        self.assertEqual(updated["effect"], "deny")
        self.assertEqual(updated["id"], original["id"])
        self.assertEqual(
            self._fetch_override_count(self.user_a, permission_id),
            1,
            "Updating an override should not create duplicate rows.",
        )

    def test_global_and_team_scoped_overrides_can_coexist(
        self,
    ) -> None:
        permission = self._create_test_permission("scoped-overrides")
        permission_id = UUID(str(permission["id"]))

        self._invoke(
            set_user_permission_override,
            user_id=self.user_a,
            permission_id=permission_id,
            effect="allow",
            team_id=None,
            assigned_by=self.user_b,
        )
        self._invoke(
            set_user_permission_override,
            user_id=self.user_a,
            permission_id=permission_id,
            effect="deny",
            team_id=self.team_a,
            assigned_by=self.user_b,
        )

        global_override = self._fetch_override(
            self.user_a,
            permission_id,
            None,
        )
        team_override = self._fetch_override(
            self.user_a,
            permission_id,
            self.team_a,
        )

        self.assertIsNotNone(global_override)
        self.assertIsNotNone(team_override)
        assert global_override is not None
        assert team_override is not None

        self.assertEqual(global_override["effect"], "allow")
        self.assertEqual(team_override["effect"], "deny")
        self.assertNotEqual(global_override["id"], team_override["id"])

    def test_set_user_permission_override_rejects_invalid_effect(
        self,
    ) -> None:
        permission = self._create_test_permission("invalid-effect")

        with self.assertRaises(
            auth_errors.InvalidAuthorizationRecordError
        ):
            self._invoke(
                set_user_permission_override,
                user_id=self.user_a,
                permission_id=UUID(str(permission["id"])),
                effect="grant",
                team_id=None,
                assigned_by=self.user_b,
            )

    def test_get_user_permission_overrides_returns_user_overrides(
        self,
    ) -> None:
        permission_a = self._create_test_permission("get-override-a")
        permission_b = self._create_test_permission("get-override-b")

        for permission in (permission_a, permission_b):
            self._invoke(
                set_user_permission_override,
                user_id=self.user_a,
                permission_id=UUID(str(permission["id"])),
                effect="allow",
                team_id=None,
                assigned_by=self.user_b,
            )

        rows = self._extract_rows(
            self._invoke(
                get_user_permission_overrides,
                user_id=self.user_a,
            )
        )

        returned_permission_ids = {
            str(self._value(row, "permission_id"))
            for row in rows
        }

        self.assertIn(str(permission_a["id"]), returned_permission_ids)
        self.assertIn(str(permission_b["id"]), returned_permission_ids)
        self.assertTrue(
            all(
                str(self._value(row, "user_id")) == str(self.user_a)
                for row in rows
            ),
            "Override listing returned records for another user.",
        )

    def test_remove_global_override_preserves_team_override(
        self,
    ) -> None:
        permission = self._create_test_permission("remove-global")
        permission_id = UUID(str(permission["id"]))

        self._invoke(
            set_user_permission_override,
            user_id=self.user_a,
            permission_id=permission_id,
            effect="allow",
            team_id=None,
            assigned_by=self.user_b,
        )
        self._invoke(
            set_user_permission_override,
            user_id=self.user_a,
            permission_id=permission_id,
            effect="deny",
            team_id=self.team_a,
            assigned_by=self.user_b,
        )

        self._invoke(
            remove_user_permission_override,
            user_id=self.user_a,
            permission_id=permission_id,
            team_id=None,
        )

        self.assertIsNone(
            self._fetch_override(self.user_a, permission_id, None)
        )

        team_override = self._fetch_override(
            self.user_a,
            permission_id,
            self.team_a,
        )
        self.assertIsNotNone(team_override)
        assert team_override is not None
        self.assertEqual(team_override["effect"], "deny")

    def test_remove_team_override_preserves_global_override(
        self,
    ) -> None:
        permission = self._create_test_permission("remove-team")
        permission_id = UUID(str(permission["id"]))

        self._invoke(
            set_user_permission_override,
            user_id=self.user_a,
            permission_id=permission_id,
            effect="allow",
            team_id=None,
            assigned_by=self.user_b,
        )
        self._invoke(
            set_user_permission_override,
            user_id=self.user_a,
            permission_id=permission_id,
            effect="deny",
            team_id=self.team_a,
            assigned_by=self.user_b,
        )

        self._invoke(
            remove_user_permission_override,
            user_id=self.user_a,
            permission_id=permission_id,
            team_id=self.team_a,
        )

        self.assertIsNone(
            self._fetch_override(
                self.user_a,
                permission_id,
                self.team_a,
            )
        )

        global_override = self._fetch_override(
            self.user_a,
            permission_id,
            None,
        )
        self.assertIsNotNone(global_override)
        assert global_override is not None
        self.assertEqual(global_override["effect"], "allow")

    # =========================================================
    # CALLER-OWNED TRANSACTION
    # =========================================================

    def test_assign_role_to_user_respects_caller_owned_transaction(
        self,
    ) -> None:
        role = self._create_test_role("transaction")
        role_id = UUID(str(role["id"]))

        with self.assertRaises(RollbackProbe):
            with get_connection() as connection:
                self._invoke(
                    assign_role_to_user,
                    user_id=self.user_a,
                    role_id=role_id,
                    assigned_by=self.user_b,
                    connection=connection,
                )

                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT COUNT(*)
                        FROM user_roles
                        WHERE user_id = %s AND role_id = %s;
                        """,
                        (self.user_a, role_id),
                    )
                    self.assertEqual(cursor.fetchone()[0], 1)

                raise RollbackProbe(
                    "Force caller-owned authorization transaction rollback."
                )

        self.assertEqual(
            self._fetch_user_role_count(self.user_a, role_id),
            0,
            "assign_role_to_user committed a transaction owned by its caller.",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)