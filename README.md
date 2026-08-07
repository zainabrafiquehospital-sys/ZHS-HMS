# Gynecology HMS

A full-stack Hospital Management System for a gynecology/maternity OPD
(outpatient department) — patient registration, doctor queueing,
consultation, vitals, billing, and printable documents, built on a
FastAPI backend and a Next.js frontend with database-enforced RBAC
throughout.

## Project Overview

This system covers the complete outpatient workflow of a real hospital
front desk:

```
Reception → Register/Search Patient → Queue Token → Doctor Consultation
  → Vitals (if required) → Return to Doctor → Complete Consultation
  → Billing → Invoice → Printed Receipt
```

Reception can register a patient in a handful of fields (name, age,
phone, procedure, amount) with no manual doctor selection — an
available doctor is assigned automatically, or the visit proceeds
unassigned and is claimed by the first doctor who opens it. Every
action is gated by a real, database-backed permission system, not just
hidden UI.

## Architecture

**Backend** — FastAPI (Python), Clean + Feature-based layering per
module: `router → service → repository → model`. SQLAlchemy (async,
`asyncpg`) over PostgreSQL, Alembic migrations, UUIDv7 primary keys,
soft delete, server-generated timestamps, audit-on-write. Every
mutating endpoint returns a standard envelope: `{"data": ..., "meta":
..., "error": ...}`.

**Frontend** — Next.js 15 (App Router), React 19, JavaScript only (no
TypeScript). TanStack Query + Axios for server state, React Hook Form +
Zod for forms, Tailwind CSS with hand-rolled shadcn-style primitives.
The access token is kept in memory only; the refresh token is an
httpOnly, `SameSite=Strict` cookie the backend sets and reads directly.

**Module dependency graph** — one-directional: `patients` / `visits` /
`queue` sit at the base; `reception` / `consultation` / `vitals` /
`billing` depend downward on those; `search` / `dashboard` are
read-only on top. No module reaches back into a module above it in
this graph.

**Database** — PostgreSQL, with Postgres `SEQUENCE`s for MR numbers and
queue tokens (never `COUNT(*) + 1`), partial unique indexes for
"single active row" invariants (one open queue entry / consultation /
invoice per visit), and `SELECT ... FOR UPDATE` row locking for
concurrent money mutations (invoice payments).

## Folder Structure

```
gynecology-hms/
├── backend/
│   ├── app/
│   │   ├── api/v1/           # Versioned router aggregation, health check
│   │   ├── core/              # Settings, JWT keys, rate limiting, middleware
│   │   ├── db/                 # Async engine/session, Alembic env, model registry
│   │   │   └── migrations/versions/
│   │   ├── modules/            # One folder per feature module (see below)
│   │   │   ├── auth/            # Users, roles, permissions, login/refresh (frozen core)
│   │   │   ├── patients/
│   │   │   ├── visits/
│   │   │   ├── queue/
│   │   │   ├── reception/
│   │   │   ├── consultation/
│   │   │   ├── vitals/
│   │   │   ├── billing/
│   │   │   ├── search/
│   │   │   └── dashboard/
│   │   ├── shared/              # Base entity, audit log, pagination, printing service
│   │   └── redis/               # Redis client factory (rate limiting, token bookkeeping)
│   ├── tests/                    # pytest — repository / service / endpoint / integration
│   ├── alembic.ini
│   ├── requirements.txt
│   └── .env.example
├── frontend/
│   ├── src/
│   │   ├── app/                  # Next.js App Router routes ((auth) / (dashboard) groups)
│   │   ├── core/                  # Providers, env config, route/permission constants
│   │   ├── features/               # One folder per feature (components/hooks/api/schemas)
│   │   │   ├── auth/
│   │   │   ├── reception/
│   │   │   ├── consultation/
│   │   │   ├── vitals/
│   │   │   ├── billing/
│   │   │   ├── patients/
│   │   │   ├── visits/
│   │   │   └── dashboard/
│   │   ├── shared/                  # Reusable UI primitives, layout shells
│   │   └── services/api/             # Axios instance, in-memory token store
│   ├── public/images/logo.png
│   ├── package.json
│   └── .env.example
├── docs/                             # Architecture reference documents
├── docker-compose.yml
└── README.md                          # This file
```

## Requirements

- **Node.js** 20+ and npm
- **Python** 3.13+
- **PostgreSQL** 17 (or compatible)
- **Redis** 7 (rate limiting and session bookkeeping)
- Docker & Docker Compose (optional — for running Postgres/Redis, or the whole stack)

## Installation

```bash
git clone <this-repository-url>
cd gynecology-hms
```

If you don't already have PostgreSQL and Redis running locally, the
fastest path is:

```bash
docker compose up -d postgres redis
```

## Backend Setup

```bash
cd backend
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env             # then edit .env — see "Environment Variables" below
```

**Generate a JWT signing key** (RS256; not committed to the repo — see
`app/core/jwt_keys.py`):

```bash
mkdir -p keys
python -c "
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
open('keys/dev.pem', 'wb').write(key.private_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PrivateFormat.PKCS8,
    encryption_algorithm=serialization.NoEncryption(),
))
"
```

Set `JWT_KEYS_DIR=./keys` and `JWT_ACTIVE_KID=dev` in `.env` (already
the default in `.env.example`) to match the filename above.

### Database Migration

```bash
alembic upgrade head
```

This applies every migration in `app/db/migrations/versions/` in
order, creating the full schema (users/roles/permissions, patients,
visits, queue, consultation, vitals, billing, audit log). Migrations
are written to be reversible — `alembic downgrade -1` reverts the most
recent one.

### Run Backend

```bash
uvicorn app.main:app --reload
```

The API runs at `http://localhost:8000`, health check at
`GET /api/v1/health`, interactive docs at `/docs`.

> **Note:** if your working copy lives inside a cloud-synced folder
> (OneDrive, Dropbox, Google Drive), `--reload`'s file watcher can
> silently stop picking up changes — the sync client interferes with
> the OS-level file-change notifications it relies on. If edits stop
> appearing in a running dev server, do a plain restart (stop the
> process, run `uvicorn app.main:app` again) instead of relying on
> `--reload`.

Run the test suite:

```bash
pip install -r requirements-dev.txt
pytest
```

## Frontend Setup

```bash
cd frontend
npm install
cp .env.example .env.local       # defaults already point at http://localhost:8000
```

### Run Frontend

```bash
npm run dev
```

The app runs at `http://localhost:3000`. Log in, and you'll land on
the module your account has permission for (Reception, Doctor Queue,
Vitals, or Billing) — see **Role-Based Access** below.

Production build:

```bash
npm run build
npm run start
```

## Environment Variables

Both `backend/.env.example` and `frontend/.env.example` are fully
commented — copy them and fill in real values. Never commit the
resulting `.env` / `.env.local` files (already gitignored).

**Backend** (`backend/.env`) — highlights:

| Variable | Purpose |
|---|---|
| `DATABASE_URL` / `DATABASE_SYNC_URL` | Postgres connection (async for the app, sync for Alembic) |
| `REDIS_URL` | Rate limiting and refresh-token bookkeeping |
| `JWT_KEYS_DIR` / `JWT_ACTIVE_KID` | RS256 signing key directory and active key id |
| `CORS_ALLOWED_ORIGINS` | Comma-separated frontend origin(s) allowed to call the API |
| `DISPLAY_TIMEZONE` | IANA zone (default `Asia/Karachi`) used to render local times on printed documents — timestamps are always stored in UTC |
| `APP_NAME` | Hospital name shown in the UI and on printed documents |

**Frontend** (`frontend/.env.local`):

| Variable | Purpose |
|---|---|
| `NEXT_PUBLIC_API_BASE_URL` | Backend origin (no trailing slash, no `/api/v1`) |
| `NEXT_PUBLIC_API_VERSION` | Must match the backend's `API_V1_PREFIX` version segment |
| `NEXT_PUBLIC_APP_NAME` | Display name shown in the UI |

Both `NEXT_PUBLIC_*` variables are bundled into client-side JavaScript
by Next.js convention and are not secrets — the app never puts an
actual secret in a frontend environment variable.

## Production Notes

- Set `APP_ENV=production` and `DEBUG=false`.
- Provision `JWT_KEYS_DIR` from a real secrets volume/manager, not a
  file checked into or shipped alongside the repo.
- Set real, unique `DATABASE_URL` / `REDIS_URL` / `CORS_ALLOWED_ORIGINS`
  credentials — the values in `docker-compose.yml` and `.env.example`
  are local-development placeholders only.
- Run the backend behind a reverse proxy (nginx, Caddy) terminating
  TLS; the refresh-token cookie is marked `Secure` automatically once
  `APP_ENV=production` (see `app/modules/auth/router.py`).
- Run `uvicorn` under a process manager (systemd, supervisor, or a
  container orchestrator) with multiple workers — not `--reload`.
- **Known dependency vulnerability:** the pinned `next@15.1.0` has
  several disclosed CVEs (including a critical Server Actions DoS and
  an RCE advisory in the React Flight protocol) fixed in later 15.x
  releases. `npm audit` flags this. Upgrading Next.js is a real code
  change (potential breaking changes across the App Router) and was
  deliberately left out of this repository-preparation pass — budget a
  dedicated, tested upgrade before or shortly after deploying publicly.

## Print System

Printable documents (the registration slip and the invoice receipt)
are rendered **server-side** as complete, self-contained HTML documents
by a shared "Central Print Service" (`app/shared/printing/service.py`)
— there is no client-side print template. The owning module (Reception,
Billing) decides *whether* a document may be printed, via the same
permission check used to view the underlying record; the print service
itself only renders.

The frontend fetches the generated HTML and opens it in a new browser
window, which then triggers the browser's native print dialog — the
same mechanism most real front-desk software relies on (no PDF library
dependency). The hospital logo is read from `frontend/public/images/`
and embedded as a `data:` URI directly in the generated HTML (not
linked by URL), so it renders identically in the live preview, the
browser's print preview, and any exported PDF regardless of the
window's origin. All timestamps are stored in UTC and converted to
`DISPLAY_TIMEZONE` only at render time.

## Authentication

RS256 JWT access tokens (short-lived, ~15 minutes) plus a rotating
refresh token delivered as an httpOnly, `SameSite=Strict` cookie
scoped to `/api/v1/auth`. The frontend never stores the access token
anywhere persistent (in-memory only — lost on page reload by design)
and silently exchanges the refresh cookie for a new access token on
load or on a 401. Account lockout after repeated failed attempts, a
configurable password-reuse history, and per-IP login rate limiting
are all enforced server-side.

## Role-Based Access

Authorization is permission-code based, not role-name based: every
protected backend endpoint requires a specific permission string (e.g.
`reception:register_visit`, `consultation:start`, `billing:manage`),
resolved from whatever roles a user currently holds. The frontend
receives the user's effective permission list on login and uses it
only to decide what to *show* — navigation links and entire routes for
a module the user lacks permission for are removed from the page
entirely, not just disabled. The backend's own permission check on
every request remains the actual authorization boundary regardless of
what the frontend renders.

## Known Modules

| Module | Responsibility |
|---|---|
| `auth` | Users, roles, permissions, login/refresh/logout, account security policy |
| `patients` | Patient identity records (MR number, demographics) |
| `visits` | One hospital encounter per patient; the visit lifecycle state machine |
| `queue` | Which worklist (reception / vitals / doctor) a visit currently sits in |
| `reception` | Composite "register a visit" / "cancel a visit" actions, registration slip |
| `consultation` | Doctor consultation lifecycle, including the vitals mid-consult detour |
| `vitals` | Recording vitals, both at intake and doctor-requested rechecks |
| `billing` | Reception-only financial authority — pending charges, invoices, payments, invoice receipt |
| `search` | Cross-module read-only patient/visit lookup |
| `dashboard` | Per-role read-only summary views (reception / doctor / vitals) |

## License

Proprietary — all rights reserved. This repository is not licensed for
reuse, redistribution, or modification outside this project unless
explicitly agreed otherwise.
