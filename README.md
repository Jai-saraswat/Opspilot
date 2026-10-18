# OpsPilot

**A web-based team operations and work management platform.**

OpsPilot is a full-stack application designed to help teams organize operational work, assign responsibility, manage priorities, and track work items throughout their lifecycle. It focuses on reliable state changes, resource-level authorization, data consistency, and maintainable backend engineering.

**Live Demo:** [https://newtonite-opspilot.vercel.app/](https://newtonite-opspilot.vercel.app/)

**Backend API:** [https://opspilot-dunh.onrender.com](https://opspilot-dunh.onrender.com)  
**API Documentation:** [OpenAPI / Swagger UI](https://opspilot-dunh.onrender.com/api/v1/docs)

---

## Overview

OpsPilot is built around a straightforward goal: make team operations easier to manage while ensuring that the underlying operations remain consistent and secure.

Rather than treating work management as a collection of basic CRUD operations, the application implements explicit business rules, authorization checks, controlled state transitions, and database-backed persistence.

The project demonstrates full-stack development, API design, relational database integration, authentication infrastructure, concurrency handling, and deployment of a frontend and backend as separate services.

## Important: Team Membership Is Required

**You must be a member of a team before you can create work items inside OpsPilot.** Creating an account alone does not make you part of a team and does not satisfy this requirement.

Join or become a member of a team first. Once you are a team member, you can create work items within the app, subject to the applicable permissions.



## Key Features

- **Work item management** — Create, assign, prioritize, track, resolve, or cancel work items.
- **Team organization** — Manage users, teams, and team memberships.
- **Access control** — Enforce authorization at the backend rather than relying on frontend visibility alone.
- **Controlled lifecycle transitions** — Apply business rules to work item state changes and retain cancelled records instead of permanently deleting them.
- **Persistent data** — Store application data in PostgreSQL so changes survive application restarts.
- **Authentication infrastructure** — Support token-based authentication and refresh-cookie handling.
- **Consistent API responses** — Return standardized success and error responses to make frontend integration predictable.
- **Operational endpoints** — Provide health and database-readiness checks for deployment and service diagnostics.
- **Web-based interface** — Access the application through a Next.js frontend connected to the FastAPI backend.

## Engineering Highlights

OpsPilot emphasizes correctness and reliability in addition to implementing user-facing features.

### 1. Backend business-rule enforcement

Application rules are enforced in the backend service layer. The frontend initiates operations, but the backend remains responsible for validating requests, checking permissions, and deciding whether an operation is allowed.

### 2. Database consistency and concurrency

The work management services were tested against PostgreSQL for persistence, authorization, stale updates, cancellation, and concurrent claims.

The concurrency tests verify that competing attempts to claim the same work item do not both succeed. This is important when multiple users may act on shared resources at the same time.

### 3. Idempotency and safe request handling

The backend includes idempotency-related configuration and request-handling support. Idempotency mechanisms help protect operations from unintended duplicate processing when clients retry requests, where the relevant operation supports that behavior.

### 4. Standardized API contracts

The API uses a consistent response structure and centralized HTTP error handling. Validation failures and unexpected errors are handled through a common response mechanism, making failures easier for clients to interpret.

### 5. Maintainable domain organization

The backend separates API routing, business services, and data operations. Domain-specific responsibilities remain organized instead of concentrating application logic in a single large endpoint file.

### 6. Deployment and configuration

The frontend and backend are deployed independently. Environment-based configuration allows the same codebase to run locally and in production without hardcoding deployment-specific settings into application code.

## Technology Stack

| Component | Technology |
|---|---|
| Frontend | Next.js, React, TypeScript |
| Styling | Tailwind CSS |
| Backend API | Python, FastAPI |
| API server | Uvicorn |
| Database | PostgreSQL |
| Database access | Psycopg |
| Authentication | Token-based authentication and secure cookie handling |
| Frontend hosting | Vercel |
| Backend hosting | Render |
| API documentation | OpenAPI / Swagger UI |

## High-Level Architecture

OpsPilot uses a decoupled frontend-backend architecture.

- **Frontend:** The Next.js application provides the user interface and communicates with the backend over HTTP.
- **Backend:** FastAPI exposes versioned API endpoints and coordinates request validation, authentication, business services, and database operations.
- **Database:** PostgreSQL stores application records and provides transactional persistence.
- **Deployment:** Vercel serves the frontend, while Render runs the backend API.

The frontend does not connect directly to PostgreSQL. Database access and business-rule enforcement remain on the backend.

## Run Locally

You can run OpsPilot from its GitHub repository if you want to inspect the implementation, develop new features, or run your own instance.

### Prerequisites

Install the following before starting:

- Git
- Python 3.10 or a compatible Python version supported by the project dependencies
- Node.js and npm
- PostgreSQL

### 1. Clone the repository

```bash
git clone https://github.com/Jai-saraswat/Opspilot.git
cd Opspilot
```

### 2. Configure PostgreSQL

Create a PostgreSQL database for your local instance.

For example, using `psql`:

```sql
CREATE DATABASE opspilot;
```

Use your own local database username and password. Ensure the application's required database schema has been applied before starting the backend. The schema files are maintained in the backend's PostgreSQL directory.

### 3. Configure backend environment variables

Create the environment file at:

```text
BACKEND/DEPLOYEMENT/.env
```

Add your local configuration:

```dotenv
DATABASE_URL=postgresql://USERNAME:PASSWORD@localhost:5432/opspilot

ACCESS_TOKEN_SECRET=replace_with_a_long_random_secret
IDEMPOTENCY_HASH_SECRET=replace_with_a_different_random_secret

ACCESS_TOKEN_TTL_SECONDS=900

FRONTEND_ORIGINS=http://localhost:3000,http://127.0.0.1:3000

AUTH_COOKIE_SECURE=false
AUTH_COOKIE_SAMESITE=lax
```

Replace the placeholder credentials and secrets with your own values. Generate separate, sufficiently long random secrets for token signing and idempotency-related hashing.

Keep this file private. **Never commit environment files, database passwords, or secret keys to GitHub.**

If your local configuration uses separate PostgreSQL variables instead of `DATABASE_URL`, configure the variables supported by the database gateway in your checkout.

### 4. Install backend dependencies

From the repository root, create and activate a virtual environment.

**Windows — PowerShell**

```powershell
py -3.10 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

If PowerShell blocks virtual environment activation, you can activate it using Command Prompt instead:

```bat
.venv\Scripts\activate.bat
```

**macOS / Linux**

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 5. Start the backend

Run the following command from the repository root:

```bash
uvicorn BACKEND.API.main:app --reload --host 127.0.0.1 --port 8000
```

The backend should now be available at:

- API base: `http://127.0.0.1:8000/api/v1`
- API documentation: `http://127.0.0.1:8000/api/v1/docs`
- Health check: `http://127.0.0.1:8000/health`
- Readiness check: `http://127.0.0.1:8000/ready`

The readiness endpoint can be used to check whether the backend can access its database.

### 6. Configure the frontend

Open a second terminal and navigate to the frontend directory:

```bash
cd frontend
```

Create a `.env.local` file inside `frontend/`:

```dotenv
NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000/api/v1
```

This variable tells the frontend which backend API to use. For local development, point it to your local FastAPI server rather than the production deployment.

### 7. Install frontend dependencies

```bash
npm install
```

### 8. Start the frontend

```bash
npm run dev
```

Open [http://localhost:3000](http://localhost:3000) in your browser.

Keep both the frontend and backend processes running while using the local application.

## Production Deployment

The public deployment is split across two services.

| Service | Deployment |
|---|---|
| Frontend | [Vercel](https://newtonite-opspilot.vercel.app/) |
| Backend | [Render](https://opspilot-dunh.onrender.com) |
| API documentation | [Swagger UI](https://opspilot-dunh.onrender.com/api/v1/docs) |

The frontend's `NEXT_PUBLIC_API_BASE_URL` must point to the deployed backend API base URL. The backend's `FRONTEND_ORIGINS` must include the exact production frontend origin.

Production secrets and database credentials should be configured through the hosting provider's environment settings, not committed to the repository.

## Testing and Validation

The backend development and validation work includes tests for:

- Account-related services and integration behavior.
- User, team, and membership operations.
- Work item persistence and lifecycle behavior.
- Authorization and stale-update handling.
- Concurrent claims and single-winner behavior.

Previously executed test runs included passing account-service integration tests, operations tests, and work-management concurrency tests against PostgreSQL. Test results may vary if the schema, configuration, or code changes.

## Project Structure

```text
Opspilot/
├── BACKEND/
│   ├── API/             # FastAPI application and routes
│   ├── Services/        # Business logic and service contracts
│   ├── Operations/      # Domain operations and data access
│   ├── Postgres/        # PostgreSQL schema and database resources
│   └── DEPLOYEMENT/     # Local environment configuration
├── frontend/            # Next.js application
├── requirements.txt     # Python dependencies
└── README.md
```

The exact contents of individual domain directories may evolve as the project develops.

## Future Improvements

Potential areas for further development include expanded operational dashboards, richer filtering and reporting, additional automated integration tests, and broader observability for production workloads.

## Author

**Jai Saraswat**

GitHub: [Jai-saraswat](https://github.com/Jai-saraswat)

---

*OpsPilot was developed as a full-stack engineering project with an emphasis on reliable work management, backend correctness, and production-oriented application practices.*
