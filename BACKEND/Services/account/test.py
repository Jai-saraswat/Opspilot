
"""OpsPilot account Services: PostgreSQL integration tests.

Run from the project root:
    python -m BACKEND.Services.account.test

Tests the real PostgreSQL database, existing seeded authorization roles,
and all 13 account service modules. Database Operations are not mocked.

Safety:
- Requires current_database() == 'opspilot'.
- Uses unique test emails.
- Cleans up only test users, their role assignments, and login sessions.
- Does not truncate tables or modify seeded roles/permissions.
"""

from __future__ import annotations

import hashlib
import os
import unittest
from uuid import UUID, uuid4

from psycopg.rows import dict_row

from BACKEND.Postgres.gateway import get_connection

from BACKEND.Services.account._common import (
    to_public_user,
    make_access_token,
    actor_is_active,
    actor_has_permission,
)
from BACKEND.Services.account.register_user import register_user
from BACKEND.Services.account.login_user import login_user
from BACKEND.Services.account.refresh_access_token import refresh_access_token
from BACKEND.Services.account.logout_user import logout_user
from BACKEND.Services.account.change_password import change_password
from BACKEND.Services.account.get_account_by_email import get_account_by_email
from BACKEND.Services.account.get_account_by_id import get_account_by_id
from BACKEND.Services.account.get_account_status import get_account_status
from BACKEND.Services.account.get_profile import get_profile
from BACKEND.Services.account.list_accounts import list_accounts
from BACKEND.Services.account.update_account import update_account
from BACKEND.Services.account.update_account_status import update_account_status
from BACKEND.Services.account.update_profile import update_profile


PASSWORD = "OpsPilotIntegrationPassword123!"
NEW_PASSWORD = "OpsPilotIntegrationPassword456!"
ADMIN_ROLE_NAME = "system_admin"
ADMIN_ROLE_SCOPE = "system"


def attr(obj, name, default=None):
    """Read either a dataclass attribute or dictionary key."""
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def data_of(response):
    """Extract ServiceOutputs.data from the real ServiceResponse contract."""
    outputs = attr(response, "outputs")
    if outputs is None:
        return None
    return attr(outputs, "data", outputs)


def error_code(response):
    error = attr(response, "error")
    return attr(error, "code")


def success_of(response):
    return attr(response, "success") is True


def assert_success(testcase, response, status=200):
    testcase.assertIsNotNone(response, "Service returned None.")
    if not success_of(response):
        testcase.fail(
            f"Expected success HTTP {status}; got "
            f"HTTP {attr(response, 'http_status')}, "
            f"error={attr(response, 'error')!r}"
        )
    testcase.assertEqual(attr(response, "http_status"), status)
    return data_of(response)


def assert_failure(testcase, response, status, code=None):
    testcase.assertIsNotNone(response, "Service returned None.")
    testcase.assertIs(
        attr(response, "success"),
        False,
        f"Expected failure; received {response!r}",
    )
    testcase.assertEqual(attr(response, "http_status"), status)
    if code is not None:
        testcase.assertEqual(error_code(response), code)


class AccountServiceDatabaseTests(unittest.TestCase):
    """Exercise all account services against the real seeded database."""

    @classmethod
    def setUpClass(cls):
        # Fail before writing anything if the wrong database is configured.
        with get_connection() as connection:
            with connection.cursor(row_factory=dict_row) as cursor:
                cursor.execute("SELECT current_database() AS db")
                row = cursor.fetchone()
                if not row or row["db"] != "opspilot":
                    raise RuntimeError(
                        "Safety check failed: expected database 'opspilot', "
                        f"found {row['db'] if row else None!r}."
                    )

                cursor.execute(
                    """
                    SELECT
                        to_regclass('public.users') AS users_table,
                        to_regclass('public.roles') AS roles_table,
                        to_regclass('public.user_roles') AS user_roles_table,
                        to_regclass('public.login_sessions') AS sessions_table;
                    """
                )
                tables = cursor.fetchone()
                missing = [key for key, value in tables.items() if value is None]
                if missing:
                    raise RuntimeError(
                        "Required database tables missing: "
                        + ", ".join(missing)
                    )

                cursor.execute(
                    """
                    SELECT id
                    FROM roles
                    WHERE name = %s AND scope = %s;
                    """,
                    (ADMIN_ROLE_NAME, ADMIN_ROLE_SCOPE),
                )
                admin_role = cursor.fetchone()
                if admin_role is None:
                    raise RuntimeError(
                        "Seeded system_admin role not found. "
                        "Check your authorization seed data."
                    )

                cursor.execute(
                    """
                    SELECT id
                    FROM roles
                    WHERE name = %s AND scope = %s;
                    """,
                    ("standard_user", "system"),
                )
                if cursor.fetchone() is None:
                    raise RuntimeError(
                        "Seeded standard_user role not found."
                    )

        print("\nUsing seeded PostgreSQL database: opspilot")

    def setUp(self):
        self.marker = uuid4().hex
        self.emails = []
        self.actor_id = None
        self.target_id = None
        self.actor_email = self.new_email("actor")
        self.target_email = self.new_email("target")

    def new_email(self, label):
        email = f"opspilot-it-{label}-{uuid4().hex}@example.invalid"
        self.emails.append(email)
        return email

    def tearDown(self):
        """Remove only accounts created by this test and their dependent rows."""
        if not self.emails:
            return

        with get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    DELETE FROM login_sessions
                    WHERE user_id IN (
                        SELECT id FROM users WHERE email = ANY(%s)
                    );
                    """,
                    (self.emails,),
                )
                cursor.execute(
                    """
                    DELETE FROM user_roles
                    WHERE user_id IN (
                        SELECT id FROM users WHERE email = ANY(%s)
                    );
                    """,
                    (self.emails,),
                )
                cursor.execute(
                    "DELETE FROM users WHERE email = ANY(%s);",
                    (self.emails,),
                )

    # ---------------------------------------------------------
    # PostgreSQL assertion helpers
    # ---------------------------------------------------------

    def db_one(self, query, parameters=()):
        with get_connection() as connection:
            with connection.cursor(row_factory=dict_row) as cursor:
                cursor.execute(query, parameters)
                row = cursor.fetchone()
                return dict(row) if row is not None else None

    def db_all(self, query, parameters=()):
        with get_connection() as connection:
            with connection.cursor(row_factory=dict_row) as cursor:
                cursor.execute(query, parameters)
                return [dict(row) for row in cursor.fetchall()]

    def register(self, email=None, name=None, password=PASSWORD):
        email = email or self.new_email("user")
        name = name or f"Integration User {uuid4().hex[:12]}"

        response = register_user(
            full_name=name,
            email=email,
            password=password,
        )
        result = assert_success(self, response, 201)
        self.assertIn("user", result)

        user = result["user"]
        user_id = UUID(str(user["id"]))

        # Independently verify the actual persisted row.
        row = self.db_one(
            """
            SELECT id, full_name, email, account_status, password_hash
            FROM users
            WHERE id = %s;
            """,
            (user_id,),
        )
        self.assertIsNotNone(row)
        self.assertEqual(str(row["id"]), str(user_id))
        self.assertEqual(row["email"], email.casefold())
        self.assertEqual(row["account_status"], "active")
        self.assertTrue(row["password_hash"])
        self.assertNotEqual(row["password_hash"], password)

        # Registration must persist the seeded standard_user assignment.
        role = self.db_one(
            """
            SELECT r.name, r.scope
            FROM user_roles AS ur
            JOIN roles AS r ON r.id = ur.role_id
            WHERE ur.user_id = %s
              AND r.name = %s
              AND r.scope = %s;
            """,
            (user_id, "standard_user", "system"),
        )
        self.assertIsNotNone(role)

        if email == self.actor_email:
            self.actor_id = user_id
        if email == self.target_email:
            self.target_id = user_id

        return user

    def create_actor_and_target(self):
        actor = self.register(self.actor_email, "Integration Actor")
        target = self.register(self.target_email, "Integration Target")
        self.actor_id = UUID(str(actor["id"]))
        self.target_id = UUID(str(target["id"]))
        return actor, target

    def grant_seeded_admin_role(self, user_id):
        """Assign the already-seeded system_admin role to a test user."""
        with get_connection() as connection:
            with connection.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    """
                    SELECT id
                    FROM roles
                    WHERE name = %s AND scope = %s;
                    """,
                    (ADMIN_ROLE_NAME, ADMIN_ROLE_SCOPE),
                )
                role = cursor.fetchone()
                self.assertIsNotNone(role)

                cursor.execute(
                    """
                    INSERT INTO user_roles (user_id, role_id, assigned_by)
                    VALUES (%s, %s, NULL)
                    ON CONFLICT DO NOTHING;
                    """,
                    (user_id, role["id"]),
                )

        # Verify the role assignment is visible to the real permission helper.
        self.assertTrue(actor_has_permission(user_id, "accounts:list"))
        self.assertTrue(actor_has_permission(user_id, "accounts:read:any"))
        self.assertTrue(actor_has_permission(user_id, "accounts:update:any"))
        self.assertTrue(
            actor_has_permission(user_id, "accounts:status:update")
        )

    def create_admin_actor_and_target(self):
        actor, target = self.create_actor_and_target()
        self.grant_seeded_admin_role(self.actor_id)
        return actor, target

    def login(self, email=None, password=PASSWORD):
        response = login_user(
            email=email or self.actor_email,
            password=password,
        )
        result = assert_success(self, response)
        self.assertTrue(result["access_token"])
        self.assertTrue(result["refresh_token"])
        return result

    def assert_public_user(self, user):
        self.assertIsInstance(user, dict)
        for forbidden in (
            "password",
            "password_hash",
            "refresh_token",
            "refresh_token_hash",
        ):
            self.assertNotIn(forbidden, user)

    # ---------------------------------------------------------
    # _common.py
    # ---------------------------------------------------------

    def test_common_public_serializer_and_active_account(self):
        user = self.register(self.actor_email, "Serializer Test")
        user_id = UUID(str(user["id"]))

        row = self.db_one(
            "SELECT * FROM users WHERE id = %s;",
            (user_id,),
        )
        public = to_public_user(row)
        self.assertEqual(public["email"], self.actor_email)
        self.assertNotIn("password_hash", public)
        self.assertTrue(actor_is_active(user_id))

    def test_common_access_token_has_valid_claims(self):
        user = self.register(self.actor_email, "JWT Test")
        user_id = UUID(str(user["id"]))

        secret = os.environ.get("ACCESS_TOKEN_SECRET", "")
        self.assertGreaterEqual(
            len(secret),
            32,
            "Set ACCESS_TOKEN_SECRET to at least 32 characters.",
        )

        import jwt

        token = make_access_token(user_id)
        claims = jwt.decode(
            token,
            secret,
            algorithms=["HS256"],
            options={"require": ["sub", "iat", "exp", "jti"]},
        )
        self.assertEqual(claims["sub"], str(user_id))
        self.assertEqual(claims["token_type"], "access")
        self.assertGreater(claims["exp"], claims["iat"])

    # ---------------------------------------------------------
    # register_user.py
    # ---------------------------------------------------------

    def test_register_user_duplicate_email_and_invalid_inputs(self):
        self.register(self.actor_email, "Duplicate Test")

        duplicate = register_user(
            full_name="Duplicate",
            email=self.actor_email,
            password=PASSWORD,
        )
        assert_failure(self, duplicate, 409, "EMAIL_ALREADY_REGISTERED")

        invalid_email = register_user(
            full_name="Invalid Email",
            email="not-an-email",
            password=PASSWORD,
        )
        assert_failure(self, invalid_email, 400, "INVALID_EMAIL")

        invalid_password = register_user(
            full_name="Invalid Password",
            email=self.new_email("invalid-password"),
            password="short",
        )
        assert_failure(self, invalid_password, 400, "INVALID_PASSWORD")

    # ---------------------------------------------------------
    # login_user.py
    # ---------------------------------------------------------

    def test_login_persists_only_hashed_refresh_token(self):
        self.register(self.actor_email, "Login Test")

        bad = login_user(
            email=self.actor_email,
            password="WrongPassword123!",
        )
        assert_failure(self, bad, 401, "INVALID_CREDENTIALS")

        login = self.login()
        digest = hashlib.sha256(
            login["refresh_token"].encode("utf-8")
        ).hexdigest()

        session = self.db_one(
            """
            SELECT id, user_id, refresh_token_hash, expires_at, revoked_at
            FROM login_sessions
            WHERE id = %s;
            """,
            (UUID(str(login["session_id"])),),
        )
        self.assertIsNotNone(session)
        self.assertEqual(str(session["user_id"]), str(self.actor_id))
        self.assertEqual(session["refresh_token_hash"], digest)
        self.assertNotEqual(session["refresh_token_hash"], login["refresh_token"])
        self.assertIsNone(session["revoked_at"])

        self.assert_public_user(login["user"])

    def test_login_rejects_unknown_email(self):
        response = login_user(
            email=self.new_email("unknown"),
            password=PASSWORD,
        )
        assert_failure(self, response, 401, "INVALID_CREDENTIALS")

    # ---------------------------------------------------------
    # refresh_access_token.py
    # ---------------------------------------------------------

    def test_refresh_access_token_works_then_rejects_revoked_session(self):
        self.register(self.actor_email, "Refresh Test")
        login = self.login()

        refreshed = refresh_access_token(
            refresh_token=login["refresh_token"]
        )
        refreshed_data = assert_success(self, refreshed)
        self.assertTrue(refreshed_data["access_token"])

        session_id = UUID(str(login["session_id"]))
        logout = logout_user(
            user_id=str(self.actor_id),
            refresh_token=login["refresh_token"],
        )
        assert_success(self, logout)

        session = self.db_one(
            "SELECT revoked_at FROM login_sessions WHERE id = %s;",
            (session_id,),
        )
        self.assertIsNotNone(session)
        self.assertIsNotNone(session["revoked_at"])

        rejected = refresh_access_token(
            refresh_token=login["refresh_token"]
        )
        assert_failure(self, rejected, 401, "INVALID_REFRESH_TOKEN")

    def test_refresh_rejects_unknown_token(self):
        response = refresh_access_token(
            refresh_token=f"unknown-{uuid4().hex}"
        )
        assert_failure(self, response, 401, "INVALID_REFRESH_TOKEN")

    # ---------------------------------------------------------
    # logout_user.py
    # ---------------------------------------------------------

    def test_logout_revokes_only_the_own_session(self):
        self.register(self.actor_email, "Logout Actor")
        self.register(self.target_email, "Logout Target")

        actor_login = self.login(self.actor_email)
        target_login = self.login(self.target_email)

        # An actor cannot revoke another user's session by presenting its token.
        response = logout_user(
            user_id=str(self.actor_id),
            refresh_token=target_login["refresh_token"],
        )
        assert_success(self, response)

        target_session = self.db_one(
            "SELECT revoked_at FROM login_sessions WHERE id = %s;",
            (UUID(str(target_login["session_id"])),),
        )
        self.assertIsNotNone(target_session)
        self.assertIsNone(target_session["revoked_at"])

        # The actor's own refresh session is revoked.
        response = logout_user(
            user_id=str(self.actor_id),
            refresh_token=actor_login["refresh_token"],
        )
        assert_success(self, response)

        actor_session = self.db_one(
            "SELECT revoked_at FROM login_sessions WHERE id = %s;",
            (UUID(str(actor_login["session_id"])),),
        )
        self.assertIsNotNone(actor_session)
        self.assertIsNotNone(actor_session["revoked_at"])

    # ---------------------------------------------------------
    # change_password.py
    # ---------------------------------------------------------

    def test_change_password_updates_hash_and_revokes_sessions(self):
        self.register(self.actor_email, "Password Test")
        login = self.login()

        before = self.db_one(
            "SELECT password_hash FROM users WHERE id = %s;",
            (self.actor_id,),
        )

        response = change_password(
            user_id=str(self.actor_id),
            current_password=PASSWORD,
            new_password=NEW_PASSWORD,
        )
        assert_success(self, response)

        after = self.db_one(
            "SELECT password_hash FROM users WHERE id = %s;",
            (self.actor_id,),
        )
        self.assertNotEqual(before["password_hash"], after["password_hash"])
        self.assertNotEqual(after["password_hash"], NEW_PASSWORD)

        session = self.db_one(
            "SELECT revoked_at FROM login_sessions WHERE id = %s;",
            (UUID(str(login["session_id"])),),
        )
        self.assertIsNotNone(session)
        self.assertIsNotNone(session["revoked_at"])

        assert_success(
            self,
            login_user(email=self.actor_email, password=NEW_PASSWORD),
        )
        assert_failure(
            self,
            login_user(email=self.actor_email, password=PASSWORD),
            401,
            "INVALID_CREDENTIALS",
        )

    def test_change_password_rejects_wrong_current_password(self):
        self.register(self.actor_email, "Wrong Current Password Test")
        response = change_password(
            user_id=str(self.actor_id),
            current_password="WrongPassword123!",
            new_password=NEW_PASSWORD,
        )
        assert_failure(self, response, 401, "INCORRECT_CURRENT_PASSWORD")

    def test_change_password_rejects_short_password(self):
        self.register(self.actor_email, "Short Password Test")
        response = change_password(
            user_id=str(self.actor_id),
            current_password=PASSWORD,
            new_password="short",
        )
        assert_failure(self, response, 400, "INVALID_NEW_PASSWORD")

    # ---------------------------------------------------------
    # get_account_by_email.py
    # ---------------------------------------------------------

    def test_get_account_by_email_allows_self_and_admin(self):
        actor, target = self.create_admin_actor_and_target()

        own = get_account_by_email(
            actor_user_id=str(self.actor_id),
            email=self.actor_email.upper(),
        )
        own_data = assert_success(self, own)
        self.assertEqual(own_data["user"]["email"], self.actor_email)

        other = get_account_by_email(
            actor_user_id=str(self.actor_id),
            email=self.target_email,
        )
        other_data = assert_success(self, other)
        self.assertEqual(
            str(other_data["user"]["id"]),
            str(self.target_id),
        )
        self.assert_public_user(other_data["user"])

    def test_get_account_by_email_forbidden_for_standard_user(self):
        self.create_actor_and_target()
        response = get_account_by_email(
            actor_user_id=str(self.actor_id),
            email=self.target_email,
        )
        assert_failure(self, response, 403, "FORBIDDEN")

    # ---------------------------------------------------------
    # get_account_by_id.py
    # ---------------------------------------------------------

    def test_get_account_by_id_allows_self_and_admin(self):
        self.create_admin_actor_and_target()

        own = get_account_by_id(
            actor_user_id=str(self.actor_id),
            target_user_id=str(self.actor_id),
        )
        own_data = assert_success(self, own)
        self.assertEqual(str(own_data["user"]["id"]), str(self.actor_id))

        other = get_account_by_id(
            actor_user_id=str(self.actor_id),
            target_user_id=str(self.target_id),
        )
        other_data = assert_success(self, other)
        self.assertEqual(str(other_data["user"]["id"]), str(self.target_id))

    def test_get_account_by_id_forbidden_for_standard_user(self):
        self.create_actor_and_target()
        response = get_account_by_id(
            actor_user_id=str(self.actor_id),
            target_user_id=str(self.target_id),
        )
        assert_failure(self, response, 403, "FORBIDDEN")

    # ---------------------------------------------------------
    # get_account_status.py
    # ---------------------------------------------------------

    def test_get_account_status_reads_real_status(self):
        self.register(self.actor_email, "Status Test")

        response = get_account_status(
            actor_user_id=str(self.actor_id),
        )
        data = assert_success(self, response)
        self.assertEqual(data["account_status"], "active")
        self.assertEqual(data["user_id"], str(self.actor_id))

        # Confirm the result agrees with the persisted record.
        row = self.db_one(
            "SELECT account_status FROM users WHERE id = %s;",
            (self.actor_id,),
        )
        self.assertEqual(data["account_status"], row["account_status"])

    def test_get_account_status_forbidden_for_other_user(self):
        self.create_actor_and_target()
        response = get_account_status(
            actor_user_id=str(self.actor_id),
            target_user_id=str(self.target_id),
        )
        assert_failure(self, response, 403, "FORBIDDEN")

    # ---------------------------------------------------------
    # get_profile.py
    # ---------------------------------------------------------

    def test_get_profile_returns_persisted_public_profile(self):
        self.register(self.actor_email, "Profile Test")

        response = get_profile(actor_user_id=str(self.actor_id))
        data = assert_success(self, response)
        self.assertEqual(data["user"]["email"], self.actor_email)
        self.assertEqual(data["user"]["full_name"], "Profile Test")
        self.assert_public_user(data["user"])

    # ---------------------------------------------------------
    # list_accounts.py
    # ---------------------------------------------------------

    def test_list_accounts_requires_permission(self):
        self.register(self.actor_email, "List Denial Test")
        response = list_accounts(actor_user_id=str(self.actor_id))
        assert_failure(self, response, 403, "FORBIDDEN")

    def test_list_accounts_reads_database_and_paginates(self):
        self.create_admin_actor_and_target()

        response = list_accounts(
            actor_user_id=str(self.actor_id),
            limit=10,
            offset=0,
            search=self.marker,
        )
        data = assert_success(self, response)

        self.assertIn("items", data)
        self.assertIn("total", data)
        self.assertEqual(data["limit"], 10)
        self.assertEqual(data["offset"], 0)

        # Search for our own unique marker independently in the result.
        response = list_accounts(
            actor_user_id=str(self.actor_id),
            limit=10,
            offset=0,
            search=self.target_email,
        )
        data = assert_success(self, response)
        returned_ids = {str(item["id"]) for item in data["items"]}
        self.assertIn(str(self.target_id), returned_ids)

        for item in data["items"]:
            self.assert_public_user(item)

    def test_list_accounts_rejects_invalid_status_filter(self):
        self.create_admin_actor_and_target()
        response = list_accounts(
            actor_user_id=str(self.actor_id),
            account_status="not-a-real-status",
        )
        assert_failure(self, response, 400, "INVALID_STATUS")

    # ---------------------------------------------------------
    # update_account.py
    # ---------------------------------------------------------

    def test_update_account_updates_another_user_in_database(self):
        self.create_admin_actor_and_target()
        new_name = f"Admin Updated {uuid4().hex[:10]}"

        response = update_account(
            actor_user_id=str(self.actor_id),
            target_user_id=str(self.target_id),
            full_name=new_name,
        )
        data = assert_success(self, response)
        self.assertEqual(data["user"]["full_name"], new_name)

        row = self.db_one(
            "SELECT full_name FROM users WHERE id = %s;",
            (self.target_id,),
        )
        self.assertIsNotNone(row)
        self.assertEqual(row["full_name"], new_name)

    def test_update_account_requires_permission(self):
        self.create_actor_and_target()
        response = update_account(
            actor_user_id=str(self.actor_id),
            target_user_id=str(self.target_id),
            full_name="Unauthorized Update",
        )
        assert_failure(self, response, 403, "FORBIDDEN")

    # ---------------------------------------------------------
    # update_account_status.py
    # ---------------------------------------------------------

    def test_update_account_status_suspends_and_revokes_sessions(self):
        self.create_admin_actor_and_target()
        target_login = self.login(self.target_email)
        session_id = UUID(str(target_login["session_id"]))

        response = update_account_status(
            actor_user_id=str(self.actor_id),
            target_user_id=str(self.target_id),
            account_status="suspended",
        )
        data = assert_success(self, response)

        self.assertEqual(data["user"]["account_status"], "suspended")

        user_row = self.db_one(
            "SELECT account_status FROM users WHERE id = %s;",
            (self.target_id,),
        )
        self.assertEqual(user_row["account_status"], "suspended")

        session_row = self.db_one(
            "SELECT revoked_at FROM login_sessions WHERE id = %s;",
            (session_id,),
        )
        self.assertIsNotNone(session_row)
        self.assertIsNotNone(session_row["revoked_at"])

        # Suspended accounts must not log in.
        response = login_user(
            email=self.target_email,
            password=PASSWORD,
        )
        assert_failure(self, response, 403, "ACCOUNT_INACTIVE")

    def test_update_account_status_prevents_self_lockout(self):
        self.register(self.actor_email, "Self Lockout Test")
        self.grant_seeded_admin_role(self.actor_id)

        response = update_account_status(
            actor_user_id=str(self.actor_id),
            target_user_id=str(self.actor_id),
            account_status="suspended",
        )
        assert_failure(self, response, 409, "SELF_LOCKOUT_PREVENTED")

        row = self.db_one(
            "SELECT account_status FROM users WHERE id = %s;",
            (self.actor_id,),
        )
        self.assertEqual(row["account_status"], "active")

    def test_update_account_status_requires_permission(self):
        self.create_actor_and_target()
        response = update_account_status(
            actor_user_id=str(self.actor_id),
            target_user_id=str(self.target_id),
            account_status="suspended",
        )
        assert_failure(self, response, 403, "FORBIDDEN")

    # ---------------------------------------------------------
    # update_profile.py
    # ---------------------------------------------------------

    def test_update_profile_persists_own_profile(self):
        self.register(self.actor_email, "Original Profile")

        new_name = f"Profile Changed {uuid4().hex[:10]}"
        response = update_profile(
            actor_user_id=str(self.actor_id),
            full_name=new_name,
        )
        data = assert_success(self, response)
        self.assertEqual(data["user"]["full_name"], new_name)

        row = self.db_one(
            "SELECT full_name, email FROM users WHERE id = %s;",
            (self.actor_id,),
        )
        self.assertEqual(row["full_name"], new_name)
        self.assertEqual(row["email"], self.actor_email)

    def test_update_profile_rejects_empty_update(self):
        self.register(self.actor_email, "No Change Test")
        response = update_profile(
            actor_user_id=str(self.actor_id),
        )
        assert_failure(self, response, 400, "NO_CHANGES")


if __name__ == "__main__":
    unittest.main(verbosity=2)
