"""Unit tests for the centralized authorization policy."""

from __future__ import annotations

import unittest
from uuid import uuid4

from BACKEND.Services.authorization.policy import (
    ActorContext,
    PermissionOverride,
    can_access_team,
    can_read_account,
    has_permission,
    has_team_role,
    require_authenticated,
    require_permission,
    AuthenticationRequiredError,
    PermissionDeniedError,
)


class AuthorizationPolicyTests(unittest.TestCase):

    def setUp(self):
        self.user_id = uuid4()
        self.other_user_id = uuid4()
        self.team_id = uuid4()
        self.other_team_id = uuid4()

    def test_system_permission_grant_is_recognized(self):
        actor = ActorContext(
            user_id=self.user_id,
            permissions=frozenset({"accounts:read:any"}),
        )

        self.assertTrue(
            has_permission(actor, "accounts:read:any")
        )

    def test_global_deny_override_beats_role_grant(self):
        actor = ActorContext(
            user_id=self.user_id,
            permissions=frozenset({"teams:manage:any"}),
            permission_overrides=(
                PermissionOverride(
                    permission="teams:manage:any",
                    effect="deny",
                ),
            ),
        )

        self.assertFalse(
            has_permission(
                actor,
                "teams:manage:any",
                self.team_id,
            )
        )

    def test_team_deny_applies_only_to_its_team(self):
        actor = ActorContext(
            user_id=self.user_id,
            permissions=frozenset({"teams:update:any"}),
            permission_overrides=(
                PermissionOverride(
                    permission="teams:update:any",
                    effect="deny",
                    team_id=self.team_id,
                ),
            ),
        )

        self.assertFalse(
            has_permission(
                actor,
                "teams:update:any",
                self.team_id,
            )
        )

        self.assertTrue(
            has_permission(
                actor,
                "teams:update:any",
                self.other_team_id,
            )
        )

    def test_team_allow_override_applies_only_to_its_team(self):
        actor = ActorContext(
            user_id=self.user_id,
            permission_overrides=(
                PermissionOverride(
                    permission="teams:update:any",
                    effect="allow",
                    team_id=self.team_id,
                ),
            ),
        )

        self.assertTrue(
            has_permission(
                actor,
                "teams:update:any",
                self.team_id,
            )
        )

        self.assertFalse(
            has_permission(
                actor,
                "teams:update:any",
                self.other_team_id,
            )
        )

    def test_global_deny_override_beats_team_allow(self):
        actor = ActorContext(
            user_id=self.user_id,
            permission_overrides=(
                PermissionOverride(
                    permission="teams:update:any",
                    effect="allow",
                    team_id=self.team_id,
                ),
                PermissionOverride(
                    permission="teams:update:any",
                    effect="deny",
                ),
            ),
        )

        self.assertFalse(
            has_permission(
                actor,
                "teams:update:any",
                self.team_id,
            )
        )

    def test_team_permission_requires_matching_team(self):
        actor = ActorContext(
            user_id=self.user_id,
            team_permissions=frozenset({
                (self.team_id, "work_items:read:any"),
            }),
        )

        self.assertTrue(
            has_permission(
                actor,
                "work_items:read:any",
                self.team_id,
            )
        )

        self.assertFalse(
            has_permission(
                actor,
                "work_items:read:any",
                self.other_team_id,
            )
        )

    def test_team_role_requires_membership_and_matching_role(self):
        actor = ActorContext(
            user_id=self.user_id,
            team_ids=frozenset({self.team_id}),
            team_roles=frozenset({
                (self.team_id, "lead"),
            }),
        )

        self.assertTrue(
            has_team_role(actor, self.team_id, "lead")
        )
        self.assertFalse(
            has_team_role(actor, self.team_id, "approver")
        )
        self.assertFalse(
            has_team_role(actor, self.other_team_id, "lead")
        )

    def test_team_member_can_access_their_team(self):
        actor = ActorContext(
            user_id=self.user_id,
            team_ids=frozenset({self.team_id}),
        )

        self.assertTrue(can_access_team(actor, self.team_id))
        self.assertFalse(
            can_access_team(actor, self.other_team_id)
        )

    def test_global_reader_can_access_a_team(self):
        actor = ActorContext(
            user_id=self.user_id,
            permissions=frozenset({"teams:read:any"}),
        )

        self.assertTrue(can_access_team(actor, self.team_id))

    def test_self_account_access_is_allowed(self):
        actor = ActorContext(user_id=self.user_id)

        self.assertTrue(
            can_read_account(actor, self.user_id)
        )
        self.assertFalse(
            can_read_account(actor, self.other_user_id)
        )

    def test_account_read_permission_allows_other_account(self):
        actor = ActorContext(
            user_id=self.user_id,
            permissions=frozenset({"accounts:read:any"}),
        )

        self.assertTrue(
            can_read_account(actor, self.other_user_id)
        )

    def test_require_authenticated_rejects_missing_actor(self):
        with self.assertRaises(AuthenticationRequiredError):
            require_authenticated(None)

    def test_require_permission_rejects_denied_permission(self):
        actor = ActorContext(user_id=self.user_id)

        with self.assertRaises(PermissionDeniedError):
            require_permission(
                actor,
                "teams:delete:any",
                self.team_id,
            )


if __name__ == "__main__":
    unittest.main()