
# OpsPilot — Engineering Decisions

## 1. Overview

OpsPilot is a team-based operations platform for managing work items, assignments, approvals, and activity history.

The main engineering goal was to build a working system with clear responsibilities, reliable business rules, and controlled access to data. The decisions below explain the main approaches used in the project and why they were chosen.

## 2. Backend Architecture

**Decision:** Separate the backend into API, Services, and Operations layers.

- **API:** Handles HTTP requests, validates inputs, obtains the authenticated user's identity, and returns responses.
- **Services:** Implements business rules, authorization checks, and workflow decisions.
- **Operations:** Handles database operations and persistence.

**Why:** Keeping these responsibilities separate makes the code easier to understand, test, and maintain. It also avoids placing business logic directly inside API route handlers.

## 3. PostgreSQL for Data Storage

**Decision:** Use PostgreSQL as the primary database.

**Why:** OpsPilot contains related data such as users, teams, memberships, work items, approvals, and activity records. A relational database provides foreign keys, constraints, and transactions to maintain consistency between these records.

The schema also uses indexes and bounded pagination to support common queries without requiring the application to load entire datasets.

## 4. Backend-Enforced Authorization

**Decision:** Enforce permissions in the backend rather than relying on frontend visibility.

**Why:** Hiding a button in the frontend does not prevent someone from calling the API directly. Protected operations therefore require backend authorization checks.

OpsPilot distinguishes team-level responsibilities from system-level permissions. This allows actions such as managing team memberships to be restricted to appropriately authorized users.

## 5. Controlled Workflows

**Decision:** Use explicit work-item statuses and separate approval requests.

**Why:** Operational work follows a lifecycle. Not every status change or approval decision should be allowed in every situation.

Explicit states and backend validation help prevent invalid transitions. Keeping approval requests separate from work items also makes approval decisions easier to track and understand.

## 6. Concurrency and Duplicate Requests

**Decision:** Handle competing operations and repeated requests deliberately.

**Why:** Multiple users may attempt to act on the same work item, and clients may retry requests after a timeout or network failure.

OpsPilot uses database-backed correctness mechanisms for competing operations and idempotency support for applicable requests. The aim is to prevent conflicting updates and unintended duplicate effects rather than relying only on frontend checks.

## 7. Activity History

**Decision:** Record important operational actions in an activity table and preserve work-item history.

**Why:** Teams need to understand what changed, who performed an action, and when it happened.

Activity records provide a traceable history of important changes. Work items are cancelled through their lifecycle rather than being deleted, helping preserve operational context.

## 8. Frontend Structure

**Decision:** Use Next.js with a dedicated workspace interface and a shared API client.

**Why:** The application has several related areas, including work items, approvals, teams, activity, and account settings. A consistent workspace structure makes these features easier to navigate.

The shared API client centralizes communication with the backend instead of allowing each page to implement its own request-handling approach.

## 9. Validation and Testing

**Decision:** Test important business rules and failure cases, not just successful CRUD operations.

**Why:** The most significant risks in an operations platform involve unauthorized access, conflicting updates, repeated requests, and invalid workflow transitions.

Testing these behaviours provides stronger evidence of correctness than testing only whether records can be created, read, updated, and deleted.

## 10. Trade-offs and Limitations

OpsPilot was developed within a short project timeline, so the focus was on implementing the core workflows and their important correctness rules.

The current architecture provides a reasonable foundation for growth through PostgreSQL, separated backend responsibilities, indexes, and pagination. However, actual capacity has not been established through comprehensive load testing.

Further work could include broader automated regression coverage, performance testing under realistic concurrent workloads, and additional operational monitoring.

These are areas for future improvement rather than reasons to complicate the initial implementation unnecessarily.

## 11. Summary

The main engineering decisions behind OpsPilot prioritize:

- Clear separation of responsibilities.
- Consistent relational data.
- Backend-enforced authorization.
- Explicit and controlled workflows.
- Protection against conflicting and repeated operations.
- Traceable activity history.
- Testing of important correctness behaviours.

Together, these choices provide a practical foundation for a multi-user operations platform while keeping the implementation understandable and maintainable.
