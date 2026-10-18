# OpsPilot Operations Layer

**Audience:** Future developers, reviewers of the Newtonite Software Engineering Challenge, and anyone maintaining the OpsPilot backend.

**Purpose:** Explain the responsibility of every folder and file under `BACKEND/Operations/`, why the files are separated, how they should be used, and which rules belong in the Services/API layers instead.

> **Scope note:** This document describes the Operations-layer design and the file set established during implementation. It does not claim that the whole application is complete or that concurrency and error paths have already passed automated tests. The planned tests are intentionally a later step. If a file is renamed or its implementation changes, update this guide to match the repository.

---

## 1. What the Operations layer is for

The Operations layer is the backend's **database-access and persistence layer**. It contains focused functions for reading and writing individual kinds of records in PostgreSQL. It does not decide whether the current user is allowed to perform an action, whether a workflow transition is valid, or what the API should return to a client.

The intended backend flow is:

```text
API route
   ↓ validate request / authenticate user / shape HTTP response
Service
   ↓ authorize user / enforce business rules / coordinate transaction
Operations
   ↓ execute focused database operation / translate database failures
PostgreSQL gateway and connection helper
   ↓ connection and transaction lifecycle
PostgreSQL
```

### Why keep this layer separate?

- **One responsibility per operation:** A function should make its purpose clear, such as retrieving a user by ID or recording an approval decision only while it is pending.
- **Reusable persistence logic:** Multiple Services can use the same database operation without copying SQL.
- **Consistent error handling:** Each domain exposes understandable exceptions rather than requiring every caller to interpret raw PostgreSQL errors.
- **Transaction composition:** Operations accept an optional `connection`. A Service can pass one shared connection to several operations to make a multi-step business action atomic.
- **Testability:** Individual database operations and higher-level use cases can be tested separately. The later test phase should also include integration tests against PostgreSQL for behaviours that depend on locks, constraints, and transaction semantics.

### What Operations must not do

Operations are intentionally not the place for:

- Authentication, password verification, token issuance, or deciding whether an account may log in.
- Authorization policy evaluation or deciding whether a role grants an action.
- Workflow policy such as which work-item status transitions are permitted.
- Deciding whether a user is allowed to assign work in a particular team.
- Enforcing the rule that a team must always have a lead, unless a particular low-level operation is explicitly designed to be a database guard. The main policy and its concurrency handling belong in Services.
- Building HTTP responses, reading request objects, or returning FastAPI response models.
- Calling external services or performing notifications during a database transaction.

Operations may use conditional SQL to protect data integrity against races (for example, update an approval only while it is pending). The Service still decides whether the actor is authorised to request that operation.

---

## 2. Shared helper at the Operations root

### `BACKEND/Operations/_db.py`

Shared by all nine domain folders; it is not a tenth domain folder.

| Function | Responsibility | Why it exists |
|---|---|---|
| `connection_scope(connection=None)` | Uses the supplied connection, or obtains and manages one via the PostgreSQL gateway when no connection is supplied. | Supports both standalone operations and multi-operation transactions coordinated by Services. |
| `log_database_failure(logger, operation, error)` | Logs the operation name and safe diagnostic details such as SQLSTATE without logging query parameters. | Gives developers useful diagnostics while reducing the risk of leaking emails, token hashes, request bodies, or other sensitive values into logs. |

**Transaction ownership rule:** When a caller supplies `connection`, the caller owns the transaction. The operation must not commit or roll back that caller-owned transaction. Let failures propagate so the Service can roll back the complete unit of work. When no connection is supplied, `connection_scope` obtains a connection from `BACKEND.Postgres.gateway.get_connection()` and lets that connection context manage commit/rollback and closing.

**Logging note:** `log_database_failure` writes through Python's configured logging system. Unless file or external logging handlers are configured elsewhere, output normally goes to the process's configured stream (often Uvicorn/Docker logs). This helper does not itself persist logs to a file.

---

## 3. Domain folders at a glance

| Folder | Primary responsibility | Main data represented |
|---|---|---|
| `users/` | User records and basic account fields | `users` |
| `teams/` | Team records | `teams` |
| `memberships/` | The relationship between users and teams | `team_memberships` |
| `sessions/` | Refresh/login session records and revocation/expiry | `login_sessions` |
| `authorization/` | Roles, permissions, role assignment, and per-user permission overrides | `roles`, `permissions`, `role_permissions`, `user_roles`, `user_permission_overrides` |
| `work_items/` | Work-item records, filtering, assignment, priority, and status persistence | `work_items` |
| `activity/` | Append-oriented history records | `work_item_activity` |
| `approvals/` | Approval requests and conditional decisions | `work_item_approval_requests` |
| `idempotency/` | Request-key reservations, stored results, and expired-record cleanup | `idempotency_records` |

Each domain folder has its own `errors.py`. This is intentional: errors stay close to the operations that raise them, callers can catch meaningful domain errors, and the project avoids a shared inheritance hierarchy that would add complexity without a clear need.

---

## 4. File-by-file reference

## 4.1 `users/`

**Purpose:** Persist user identity and basic account information. Password hashing and verification belong in the authentication/Services layer; the Operations layer stores and retrieves the hash but should not generate or verify it.

### `users/errors.py`

Defines the user-domain exceptions, including errors for duplicate users, invalid user records, missing related records where applicable, and database failures. Keeping these exceptions local prevents user-specific failure cases from being mixed with unrelated team or session errors.

### `users/create_user.py`

Creates a user record and returns safe user fields. It translates the case-insensitive email uniqueness constraint (`uq_users_email_lower`) into a domain-level duplicate-user error and maps applicable check-constraint failures to an invalid-record error. The returned public record must not expose `password_hash`.

**Why separate:** User creation is a distinct write path with important uniqueness and privacy requirements. Authentication code can create a password hash first and then pass the hash into this operation without coupling the operation to a password library.

### `users/get_user_by_id.py`

Retrieves a user by UUID for profile, account, or related workflows. A missing user is represented consistently (typically `None`) rather than treated as an unexpected database failure.

**Why separate:** ID lookups are common and should not require callers to write SQL or retrieve sensitive authentication fields unnecessarily.

### `users/get_user_by_email.py`

Retrieves a user by email for application-facing lookups, using the email matching convention supported by the schema and implementation. It should return only fields appropriate for ordinary user operations, not a password hash or other authentication-only data.

**Why separate:** A general user lookup has a different data-exposure contract from authentication's credential lookup.

### `users/get_user_auth_record_by_email.py`

Retrieves the authentication-specific record for an email address, including the password hash and fields needed by the authentication flow. This result must remain within trusted backend authentication code and must never be returned directly from a public API endpoint.

**Why separate:** It makes the sensitive purpose explicit and reduces accidental use of authentication fields in ordinary user lookups.

### `users/list_users.py`

Lists users with server-side filtering/search and bounded pagination, according to the implementation's supported parameters. It should not load the entire users table into application memory.

**Why separate:** Administrative lists and selection controls need a reusable query that scales as the user count grows.

### `users/update_user_profile.py`

Updates profile fields such as the user's display name and email, according to the schema and the fields exposed by the operation. Omitted fields should not accidentally overwrite stored data. Email updates must continue to respect the case-insensitive unique index.

**Why separate:** Profile edits have different validation and data-exposure needs from password changes or status changes.

### `users/update_user_password_hash.py`

Stores a newly generated password hash. The caller is responsible for using an appropriate password-hashing function (the project decision is Argon2id through `pwdlib[argon2]`) before calling this operation.

**Why separate:** Credential updates should be isolated from profile updates, and password material should never be logged or returned in normal operation results.

### `users/update_user_status.py`

Changes the account state, such as `active`, `suspended`, or `deactivated`, subject to the database's allowed values.

**Why separate:** Account-status changes have security implications and should be auditable and separately authorised in Services. Deactivation is generally safer than hard-deleting a user whose identity is referenced by work items, sessions, or history.

---

## 4.2 `teams/`

**Purpose:** Persist teams and support team administration. The creation of a team and the initial membership of its creator as team lead is a higher-level workflow and should be coordinated atomically by a Service.

### `teams/errors.py`

Defines team-domain errors such as `TeamAlreadyExistsError`, `InvalidTeamRecordError`, `TeamCreatorNotFoundError`, `TeamInUseError`, and `TeamDatabaseError`. These allow Services to distinguish a name conflict from a relationship restriction or an unexpected persistence failure.

### `teams/create_team.py`

Creates the team record and returns the saved team data. It handles the team's uniqueness and validation constraints.

**Why separate:** Team creation has its own validation and uniqueness rules. The Service should combine this operation with `add_team_member` to establish the creator's lead membership within one transaction.

### `teams/get_team_by_id.py`

Retrieves a team by UUID. It supports team settings, membership workflows, authorization-context loading, and work-item-related checks.

### `teams/get_team_by_name.py`

Retrieves a team by its name using the schema's current name-matching convention. The team-name unique constraint is case-sensitive in the current schema unless the SQL is changed.

**Why separate from ID lookup:** Name-based discovery and ID-based retrieval are different lookup patterns and have different caller inputs.

### `teams/list_teams.py`

Returns a paginated/filterable set of teams using database-side queries rather than loading every team first.

**Why separate:** Team pickers and administrative screens can share a bounded query while applying different authorization in Services.

### `teams/update_team.py`

Updates supported team fields, including handling an omitted description differently from an explicit `description=None` when the latter means clearing the description. The implementation uses a sentinel to distinguish these states.

**Why separate:** Patch-style updates need to distinguish “leave unchanged” from “set to null.” Without that distinction, clients cannot reliably clear optional fields.

### `teams/delete_team.py`

Attempts to delete a team and translates the foreign-key restriction (including teams still referenced by work items) into a domain-level `TeamInUseError` where appropriate. Memberships and team-scoped permission overrides are configured to cascade according to the schema.

**Why separate:** Deletion has distinct referential-integrity outcomes. Services should still enforce business policies before deletion and return a clear response if the team remains in use.

---

## 4.3 `memberships/`

**Purpose:** Manage which users belong to which teams and the membership-level role (`lead`, `member`, or `approver`). Membership is a separate domain from user records because one user may belong to multiple teams with different responsibilities.

### `memberships/errors.py`

Defines membership-domain exceptions such as `MembershipAlreadyExistsError`, `InvalidMembershipRecordError`, `MembershipRelatedRecordNotFoundError`, and `MembershipDatabaseError`.

### `memberships/add_team_member.py`

Creates a team membership, including the selected membership role. The unique team/user constraint prevents duplicate memberships.

**Why separate:** Adding a person to a team is a relationship write, not a modification of the user or team record itself.

### `memberships/get_membership.py`

Retrieves the membership record for a specific user/team pair. It is useful when a Service needs to determine the user's membership context or validate a role change.

### `memberships/list_team_members.py`

Lists members for a team with bounded pagination and supported filtering/search. This prevents membership screens from loading unbounded relationship data.

### `memberships/list_user_teams.py`

Lists the teams a particular user belongs to. It supports a user's team switcher and team-context resolution in higher layers.

**Why separate from team-member listing:** The two queries traverse the same relationship from opposite directions and are used by different application flows.

### `memberships/update_membership_role.py`

Changes a member's team-level role. It persists the supplied role but does not by itself decide whether the current actor is entitled to promote or demote someone.

**Why separate:** Role changes have distinct auditing and authorisation requirements. Services must prevent unsafe cases such as removing or demoting the last team lead, ideally using appropriate row locking and a shared transaction.

### `memberships/remove_team_member.py`

Removes a user's membership in a team. It does not itself define whether a particular removal is permitted.

**Why separate:** Membership removal is a relationship deletion with important business-policy implications. Services must enforce rules such as preserving a team lead and handling any assignment/approval relationships affected by removal.

---

## 4.4 `sessions/`

**Purpose:** Store server-side login/refresh-session records. The schema stores a hash of the refresh token rather than the raw token. Token creation, hashing, signature validation, expiry interpretation, and authentication policy belong in the authentication/Services layer.

### `sessions/errors.py`

Defines session-domain exceptions such as `InvalidSessionRecordError`, `SessionUserNotFoundError`, and `SessionDatabaseError`.

### `sessions/create_session.py`

Creates a session for a user, storing the refresh-token hash and its expiry. It should return session metadata, not the raw refresh token.

**Why separate:** Session creation is security-sensitive and distinct from user creation or credential verification. Services must validate token lifecycle rules and pass only the hash into persistence.

### `sessions/get_session_by_id.py`

Retrieves a session record by session UUID for trusted session-management operations.

### `sessions/get_session_by_token_hash.py`

Looks up a session using the stored refresh-token hash. Callers should hash/derive the lookup value through the intended authentication flow and must never log token contents.

**Why separate from ID lookup:** Authentication usually starts with a presented refresh token, while administration may start with a session identifier.

### `sessions/list_user_sessions.py`

Lists the sessions associated with one user, enabling session-management screens and security workflows. Results should be bounded/paginated if the interface can display many sessions.

### `sessions/revoke_session.py`

Revokes one session, generally preserving an existing `revoked_at` value rather than changing the original revocation timestamp on repeated requests. This makes revocation safe to repeat.

### `sessions/revoke_user_sessions.py`

Revokes all applicable sessions for a user, supporting operations such as account suspension, password-reset response, or “log out everywhere.” The Service decides when this broad action is warranted.

**Why separate from single-session revocation:** The scope and consequences differ, and the mass update should be explicit in the calling code.

### `sessions/delete_expired_sessions.py`

Deletes expired session rows in bounded batches. The query uses a locking/batch pattern such as `FOR UPDATE SKIP LOCKED` so concurrent cleanup workers can avoid competing for the same rows.

**Why separate:** Cleanup should not load every expired record into Python and should not require a background worker for ordinary authentication. It can be called by a scheduled maintenance task later if desired.

---

## 4.5 `authorization/`

**Purpose:** Persist the role-based permission catalogue, role assignments, role-permission relationships, and user-specific permission overrides. This folder provides data operations only; it is not the complete authorization policy engine.

The current schema has both `team_memberships.role` and a separate role/permission system. Services must define one explicit policy for how those sources interact and how global and team-scoped decisions are evaluated. Do not assume the database tables alone enforce authorization.

### `authorization/errors.py`

Defines authorization-domain exceptions such as `RoleAlreadyExistsError`, `InvalidAuthorizationRecordError`, `AuthorizationRelatedRecordNotFoundError`, and `AuthorizationDatabaseError`.

### `authorization/create_role.py`

Creates a role with its scope and descriptive metadata. Role creation should generally be restricted to setup/administrative workflows rather than available to ordinary users.

### `authorization/get_role_by_id.py`

Retrieves a role by UUID for assignment, editing, or permission-management workflows.

### `authorization/get_role_by_name.py`

Retrieves a role by its name and scope. The scope matters because a role name may be meaningful within a system-wide or team-specific context.

### `authorization/list_roles.py`

Lists roles with relevant scope/filter support. It gives administrative interfaces a bounded query without exposing internal tables directly to routes.

### `authorization/get_permission_by_key.py`

Retrieves one permission from the known permission catalogue by its stable key. Permission keys should be defined/seeded by the application, not improvised independently by arbitrary endpoints.

### `authorization/list_permissions.py`

Lists the known permission catalogue, mainly for role configuration, administration, or diagnostics.

### `authorization/list_role_permissions.py`

Retrieves the permissions attached to a role by joining the role/permission relationship. The result helps the policy layer build or explain a role's permissions.

### `authorization/list_user_roles.py`

Retrieves roles assigned to a user. The policy layer combines this information with scope, team membership, and any permission overrides to decide access.

### `authorization/assign_role_to_user.py`

Creates a user/role assignment. Its insert is designed to be safe against a duplicate relationship (for example, by using `ON CONFLICT DO NOTHING`). The Service must check that the assignment is valid and authorised.

### `authorization/remove_role_from_user.py`

Removes a user/role relationship. It does not decide whether the actor is authorised or whether any required administrator/lead role would be removed.

### `authorization/add_permission_to_role.py`

Adds a permission to a role, using duplicate-safe insertion. The permission must exist in the known catalogue, and the caller should be a trusted role-management flow.

### `authorization/remove_permission_from_role.py`

Removes a permission/role relationship. Keeping this operation separate makes role-permission mutations explicit and independently auditable at the Service layer.

### `authorization/set_user_permission_override.py`

Creates or updates a user-specific `allow` or `deny` override, optionally scoped to a team. It relies on the database's unique constraint for global/team-scoped uniqueness (including `UNIQUE NULLS NOT DISTINCT` where configured).

**Why separate from role assignment:** Overrides are exceptions to the role-based policy and have different precedence and audit implications. The policy layer must explicitly define whether a deny wins over an allow and how team-scoped overrides interact with global permissions.

### `authorization/get_user_permission_overrides.py`

Retrieves the override records for a user, optionally filtered by scope according to the implementation. The policy layer uses these records when calculating effective permissions.

### `authorization/remove_user_permission_overrides.py`

Removes a particular user permission override. It must identify the appropriate global/team-scoped record without accidentally deleting a different scope's override.

---

## 4.6 `work_items/`

**Purpose:** Persist the operational requests that are central to OpsPilot. Work items include their title, description, type, status, priority, team, creator, optional assignee, timestamps, and completion time. The database schema constrains allowed types, statuses, priorities, and the relationship between `resolved` status and `completed_at`.

Operations expose database mutations; Services must enforce allowed workflow transitions and verify that the acting user and any assignee are eligible for the relevant team.

### `work_items/errors.py`

Defines work-item-domain exceptions such as `InvalidWorkItemRecordError`, `WorkItemRelatedRecordNotFoundError`, and `WorkItemDatabaseError`.

### `work_items/create_work_item.py`

Creates the work-item record and returns the persisted work-item data. It validates input expected by the database and translates relevant constraint failures into operation-level errors.

**Why separate:** Work-item creation is a principal business action and is typically coordinated by a Service with an activity entry and, when required, an idempotency response in the same transaction.

### `work_items/get_work_item_by_id.py`

Retrieves one work item by UUID. The API/Services layer must first/also enforce resource-level access; knowing a valid UUID must not grant access to a work item from another team.

### `work_items/list_work_items.py`

Retrieves a server-filtered and paginated work-item list. Common dimensions include team, status, priority, assignee, and text/query filtering where implemented. Results should use database indexes and bounded page sizes rather than fetching all work items for filtering in Python or the browser.

**Why separate:** The challenge expects a useful overview and search/filter experience as the data grows. A dedicated listing operation makes pagination and query plans easier to tune.

### `work_items/update_work_item.py`

Updates supported general fields (such as title, description, or type) and uses a supplied expected timestamp to detect stale data. An unset sentinel distinguishes “field not provided” from an explicit value.

**Concurrency note:** The current design uses `updated_at` as an optimistic concurrency marker. Ensure that timestamp precision survives database/API/frontend round trips. A monotonically incrementing integer `version` is a possible future improvement if timestamp equality proves fragile.

### `work_items/update_work_item_assignee.py`

Updates the assignee using explicit expected-state conditions, such as the expected current assignee and expected update timestamp. It is the single low-level assignee update operation for claiming an unassigned work item and for an authorised reassignment workflow; the expected values and policy are supplied by the caller.

**Why one operation instead of separate claim/assign SQL files:** Both actions change the same `assignee_id`. Keeping the low-level mutation unified avoids duplicated SQL and divergent concurrency behaviour. Services still expose different intent: a claim should only succeed if the item remains unassigned, whereas a manager reassignment may permit replacing an existing assignee after authorization.

### `work_items/update_work_item_status.py`

Updates status conditionally and manages `completed_at` consistently with the target status. The expected update timestamp guards against overwriting a newer version of the item.

**Important boundary:** A conditional status update is not, by itself, a workflow engine. Services must check that the requested transition is allowed (for example, whether approval is required) before calling this operation.

### `work_items/update_work_item_priority.py`

Changes priority with stale-state protection. Services must decide whether the actor has permission to change priority and should coordinate the change with an activity event in the same transaction.

---

## 4.7 `activity/`

**Purpose:** Store the history of important events associated with work items. Activity is intended to be append-oriented: operations are provided for creating and reading events, not editing or deleting them through normal application paths. The schema includes the work item, optional actor, action name, JSONB details, and creation timestamp.

### `activity/errors.py`

Defines activity-domain exceptions such as `InvalidActivityRecordError`, `ActivityRelatedRecordNotFoundError`, and `ActivityDatabaseError`.

### `activity/create_activity.py`

Creates an activity event and serializes its `details` into JSONB. `actor_id` may be `None` for a system-generated event where the schema allows it.

**Transaction rule:** For a significant work-item mutation, call this function using the same connection as the mutation so the state change and history entry commit or roll back together.

### `activity/get_activity_by_id.py`

Retrieves an activity event by its UUID for internal workflows or detailed history views. Resource authorization still belongs in Services/API.

### `activity/list_work_item_activity.py`

Lists activity events for one work item, ordered and paginated according to the query. The `(work_item_id, created_at)` index supports the common history timeline access pattern.

### `activity/list_user_activity.py`

Lists activity events associated with an actor/user, using bounded query behaviour. This can support audit or “my recent actions” views without scanning the entire activity history in application memory.

**Audit limitation:** Append-only application design is not the same as database-enforced immutability. Stronger guarantees would require database privileges, triggers, or another policy that prevents direct updates/deletes by the application's database role.

---

## 4.8 `approvals/`

**Purpose:** Persist approval requests and their current decision state. The schema tracks the work item, requester, optional approver, pending/approved/rejected status, reason, request time, and decision time. The current schema captures who performed an action through activity history rather than a dedicated `decided_by` column.

### `approvals/errors.py`

Defines approval-domain exceptions such as `InvalidApprovalRecordError`, `ApprovalRelatedRecordNotFoundError`, and `ApprovalDatabaseError`.

### `approvals/create_approval_request.py`

Creates an approval request for a work item. Services must confirm that the work item is eligible for approval, the requester is authorised, and any requested approver is appropriate.

### `approvals/get_approval_request_by_id.py`

Retrieves one approval request by UUID for decision workflows or detail views.

### `approvals/list_pending_approvals.py`

Lists approval requests whose status is pending, with supported filters and bounded pagination. The Service should apply the current user's authorisation and eligibility rules before returning results.

### `approvals/list_work_item_approvals.py`

Lists approval requests associated with a specific work item, supporting the item's decision/history view.

### `approvals/list_user_approval_requests.py`

Lists approval requests associated with a user in the relevant requester/approver relationship, according to the query's documented semantics. It supports personal approval queues and request tracking.

### `approvals/assign_approval_approver.py`

Assigns or changes the approver while the approval request is still pending; the operation can clear the approver when `None` is a supported input. The Service decides whether the actor can make that assignment and whether the selected user is an eligible approver.

### `approvals/record_approval_decision_if_pending.py`

Records an approval or rejection only when the current database status is `pending`. The conditional update ensures competing/repeated decisions cannot both overwrite the same pending request; the unsuccessful caller receives no updated row and the Service can return a conflict/state-change result.

**Transaction rule:** If a decision also changes the work item's status and adds activity, all related writes should share one transaction. Services must also define how multiple pending approval requests for one work item interact; the present schema does not, by itself, guarantee only one pending request per work item.

---

## 4.9 `idempotency/`

**Purpose:** Persist idempotency keys and request results so a client retry can receive the original response instead of repeating a database-changing action. The key is scoped to a user, and each record stores a request hash, optional response status/body, creation time, and expiry.

Idempotency is intended for selected write endpoints where duplicate execution would be harmful. It is not necessary on every read operation and does not by itself make external side effects (such as email delivery) exactly-once.

### `idempotency/errors.py`

Defines idempotency-specific exceptions such as `InvalidIdempotencyRecordError`, `IdempotencyKeyReuseError`, `IdempotencyRecordNotFoundError`, `IdempotencyRecordExpiredError`, `IdempotencyAlreadyCompletedError`, and `IdempotencyDatabaseError`.

### `idempotency/reserve_idempotency_key.py`

Atomically attempts to reserve a `(user_id, idempotency_key)` pair, renew an expired reservation when allowed, or identify the state of an existing request. The request hash is expected to be a lowercase, 64-character SHA-256 digest of a canonical representation of the request.

Expected states:

- `reserved`: this call created or renewed the reservation; the caller may proceed with the operation.
- `replay`: a completed matching request exists; the Service should return the saved response rather than execute the business operation again.
- `in_progress`: the same key and request hash exist but no final response has been recorded; the Service must not blindly execute the work a second time.

If the same key is reused with a different request hash, the operation raises `IdempotencyKeyReuseError`.

### `idempotency/get_idempotency_record.py`

Retrieves an idempotency record by user and key. It supports the Service's retry/recovery logic and diagnostics without duplicating record lookup SQL in multiple places.

### `idempotency/complete_idempotency_record.py`

Stores the final response status and body for an active reservation. The response body is stored as JSONB. The completion check relies on `response_status` to distinguish completed from incomplete records because a legitimate JSON response body can itself be JSON `null`, which is distinct from SQL `NULL`.

**Transaction rule:** For a database-only write, the Service should reserve the key, perform the business mutation, create the activity event, and store the final response using the **same connection and transaction**. If the operation fails before commit, the whole transaction can roll back. The frontend/client must reuse the same key only when retrying the same submission and generate a new key for a new intentional submission.

### `idempotency/delete_expired_idempotency_records.py`

Deletes expired idempotency records in bounded batches, using a database-side selection/deletion pattern to avoid loading all expired rows into application memory and to cooperate with concurrent cleanup workers.

**Limitations:** The exact response replay behaviour must be implemented by Services/API, including which HTTP status/body/headers are persisted. This table does not make external network calls transactional; reliable external side effects would need their own approach if later introduced.

---

## 5. Common implementation conventions

### Optional connection parameter

Most write/read operations accept `connection: psycopg.Connection | None = None`.

- **No connection supplied:** The operation obtains and manages a connection via `connection_scope`.
- **Connection supplied:** The operation participates in the caller-owned transaction and must not commit independently.

Use the supplied connection when several operations must succeed or fail together, such as:

```text
create/update work item
       +
create activity event
       +
complete idempotency record (where applicable)
       ↓
one commit
```

Do not run network calls or expensive external work while holding a database transaction open.

### Missing rows versus errors

Operations should use a consistent, documented return behaviour for missing rows (commonly `None`) and raise domain-specific errors only for conditions the caller needs to handle as errors. A zero-row conditional update can mean the item was missing or its state changed; Services can perform a follow-up read when the product/API needs to distinguish those cases. Avoid treating all zero-row updates as generic database failures.

### Database errors

Translate known constraints into domain errors when useful to callers. Keep unknown PostgreSQL failures as a domain database error and log SQLSTATE/operation safely. Do not expose raw SQL, database credentials, full request bodies, password hashes, or refresh-token values to API clients or routine logs.

### Pagination and scale

List operations should filter, sort, and paginate in SQL. Apply a sensible maximum page size in the Service/API layer, and ensure filters align with useful indexes. Do not fetch tens of thousands of records and filter them in Python or the browser.

### Authorization and tenant/team boundaries

Database operation functions are not a substitute for resource-level authorization. A Service must verify the acting user can access the work item's team and perform the requested action before invoking protected operations. Apply the same rule to list/detail/history/approval endpoints to avoid insecure direct-object access.

### Audit consistency

For important state changes, write the corresponding activity event in the same transaction. If either statement fails, the transaction should roll back rather than leave a changed work item without history or a history event for a failed mutation.

---

## 6. Suggested caller patterns

These are conceptual flows, not a claim that every Service has already been implemented.

### Create a work item

```text
API validates request and authenticates actor
Service verifies actor's permission and team membership
Service opens transaction / obtains connection
  reserve idempotency key if the endpoint uses it
  create_work_item(connection=...)
  create_activity(connection=...)
  complete_idempotency_record(connection=...) if applicable
Service commits and returns the intended API response
```

### Claim a work item

```text
API authenticates actor
Service verifies actor belongs to the correct team and may claim work
Service calls update_work_item_assignee with expected assignee = unassigned
and the expected current update marker
If the conditional update returns no row, treat it as a lost race or stale state
On success, write activity in the same transaction
```

### Record an approval decision

```text
API authenticates actor
Service loads/checks approval and verifies approver eligibility
Service conditionally records decision only while pending
If no row is updated, report conflict/already-decided state
If successful, update work item if workflow rules require it and create activity
Commit all related writes together
```

---

## 7. Risks and decisions that must remain visible to future developers

1. **Operations is not the whole backend.** Complete Services/API logic is required for authorization, workflow validity, transactional composition, HTTP semantics, and end-to-end idempotency.
2. **Last-team-lead policy is not automatic.** The membership database constraints do not by themselves ensure a team always retains a lead. Services need concurrency-safe enforcement if that is a product rule.
3. **Assigned user/team consistency is not enforced by the current schema alone.** Services must verify the assignee belongs to the work item's team, or the schema should be strengthened to enforce the relationship.
4. **`updated_at` concurrency markers need precision awareness.** Round-tripping a timestamp through a JavaScript client may lose PostgreSQL precision. Consider a version counter if required.
5. **Membership roles and RBAC roles are two models.** Define clear precedence and scope rules instead of letting endpoints interpret them differently.
6. **Activity is append-only by application convention, not necessarily by database privilege.** Stronger immutability requires database-level protection.
7. **Approval uniqueness/workflow is not fully encoded in the schema.** Services must define how repeated or multiple pending requests behave.
8. **Idempotency requires a shared transaction for database-only operations.** Reserving a key and then committing the business write separately leaves failure windows. A stored key alone does not guarantee duplicate prevention.
9. **Cleanup operations should be bounded.** Avoid large unbounded deletion jobs that lock too many rows.
10. **Automated tests are a planned next phase.** High-risk tests should include competing claims, stale updates, transaction rollback of activity writes, idempotent retries and key reuse, unauthorized cross-team access, and repeated approval decisions. Until run, these are test targets rather than verified guarantees.

---

## 8. Complete Operations file inventory

The intended inventory is **nine domain folders plus the shared `_db.py` helper**. The file lists below are the authoritative inventory for this document.

```text
BACKEND/Operations/
├── _db.py
├── users/
│   ├── errors.py
│   ├── create_user.py
│   ├── get_user_by_id.py
│   ├── get_user_by_email.py
│   ├── get_user_auth_record_by_email.py
│   ├── list_users.py
│   ├── update_user_profile.py
│   ├── update_user_password_hash.py
│   └── update_user_status.py
├── teams/
│   ├── errors.py
│   ├── create_team.py
│   ├── get_team_by_id.py
│   ├── get_team_by_name.py
│   ├── list_teams.py
│   ├── update_team.py
│   └── delete_team.py
├── memberships/
│   ├── errors.py
│   ├── add_team_member.py
│   ├── get_membership.py
│   ├── list_team_members.py
│   ├── list_user_teams.py
│   ├── update_membership_role.py
│   └── remove_team_member.py
├── sessions/
│   ├── errors.py
│   ├── create_session.py
│   ├── get_session_by_id.py
│   ├── get_session_by_token_hash.py
│   ├── list_user_sessions.py
│   ├── revoke_session.py
│   ├── revoke_user_sessions.py
│   └── delete_expired_sessions.py
├── authorization/
│   ├── errors.py
│   ├── create_role.py
│   ├── get_role_by_id.py
│   ├── get_role_by_name.py
│   ├── list_roles.py
│   ├── get_permission_by_key.py
│   ├── list_permissions.py
│   ├── list_role_permissions.py
│   ├── list_user_roles.py
│   ├── assign_role_to_user.py
│   ├── remove_role_from_user.py
│   ├── add_permission_to_role.py
│   ├── remove_permission_from_role.py
│   ├── set_user_permission_override.py
│   ├── get_user_permission_overrides.py
│   └── remove_user_permission_override.py
├── work_items/
│   ├── errors.py
│   ├── create_work_item.py
│   ├── get_work_item_by_id.py
│   ├── list_work_items.py
│   ├── update_work_item.py
│   ├── update_work_item_assignee.py
│   ├── update_work_item_status.py
│   └── update_work_item_priority.py
├── activity/
│   ├── errors.py
│   ├── create_activity.py
│   ├── get_activity_by_id.py
│   ├── list_work_item_activity.py
│   └── list_user_activity.py
├── approvals/
│   ├── errors.py
│   ├── create_approval_request.py
│   ├── get_approval_request_by_id.py
│   ├── list_pending_approvals.py
│   ├── list_work_item_approvals.py
│   ├── list_user_approval_requests.py
│   ├── assign_approval_approver.py
│   └── record_approval_decision_if_pending.py
└── idempotency/
    ├── errors.py
    ├── reserve_idempotency_key.py
    ├── get_idempotency_record.py
    ├── complete_idempotency_record.py
    └── delete_expired_idempotency_records.py
```

`claim_work_item_if_unassigned.py` and `assign_work_item.py` are not listed as separate final Operations files. The low-level SQL mutation was intentionally consolidated into `update_work_item_assignee.py`; Services can still implement distinct claim and reassignment use cases by passing different expected-state conditions and applying different authorisation rules.

---

## 9. How this layer supports the challenge

The Operations design supports several challenge-critical behaviours, provided the Services/API layer coordinates them correctly:

- **Concurrent claims:** conditional assignee updates let the database decide which claimant wins.
- **Stale updates:** expected-state conditions can reject an update based on old data.
- **Duplicate requests:** idempotency records can return a previously saved result for a matching retry.
- **Approval races:** pending-only decision updates let only one decision transition the row out of `pending`.
- **Auditable changes:** activity records can be committed atomically with the state change.
- **Large datasets:** server-side pagination and indexed filtering avoid loading every row into the application or browser.
- **Resource-level authorization:** the data model supports users, teams, memberships, roles, and overrides; enforcement still has to be performed by Services/API and verified with tests.

The engineering objective is not to maximise the number of database functions. It is to keep persistence code understandable, compose it correctly into transactions, and demonstrate through later integration tests that the critical behaviours remain correct under retries, concurrent requests, and failure.
