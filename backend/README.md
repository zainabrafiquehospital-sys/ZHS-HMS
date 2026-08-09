# Gynecology HMS — Backend

FastAPI (Python 3.13+) backend for the Gynecology HMS. See the
[repository root README](../README.md) for the full project overview,
architecture, environment variables, and setup instructions — this
file covers backend-specific structure and conventions only.

## Structure

- `app/main.py` — application factory; creates and configures the `FastAPI` instance.
- `app/core` — settings, JWT key registry, rate limiting, structured logging, middleware, exception classes/handlers, shared dependency-injection functions.
- `app/db` — SQLAlchemy async engine/session setup, the shared declarative base, the centralized model registry, and the Alembic migration environment.
- `app/redis` — Redis client factory (rate limiting, refresh-token bookkeeping).
- `app/api/v1` — versioned API router aggregation and the health check endpoint.
- `app/modules` — feature modules: `auth`, `patients`, `visits`, `queue`, `reception`, `consultation`, `vitals`, `billing`, `search`, `dashboard`. Each owns its own `router.py`, `schemas.py`, `service.py`, `repository.py`, `models.py`, and `exceptions.py`.
- `app/shared` — generic, entity-agnostic repository/service base classes, the shared audit log, pagination helpers, and the Central Print Service (`app/shared/printing/`).
- `tests` — pytest suite: repository-, service-, and endpoint-level tests per module, plus a full OPD integration suite (`test_opd_integration.py`) covering the end-to-end workflow under real concurrent load.
- `scripts` — one-time operational scripts, not part of the application itself (e.g. `seed_launch_bootstrap.py` — see below).

## Getting Started

```bash
cp .env.example .env
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
alembic upgrade head
python scripts/seed_launch_bootstrap.py   # first time only — see below
uvicorn app.main:app --reload
```

The API runs at http://localhost:8000, with the health check at
`GET /api/v1/health` and interactive docs at `/docs`.

### First-time bootstrap

A freshly migrated database has zero Permission/Role/User rows —
Role/Permission CRUD is only reachable through the Users/Roles/
Permissions API itself, which nobody can call before a first admin
account exists. `scripts/seed_launch_bootstrap.py` is the one-time
fix: it creates the full Permission catalog, an `admin` role holding
every permission, a `Receptionist` role scoped to exactly the
reception-slip-generation workflow, one initial admin user, and one
receptionist account — printing both accounts' randomly generated
passwords to stdout exactly once. It's idempotent (safe to re-run
against a partially-seeded database) and fully documented in its own
module docstring, including exactly which permissions the
`Receptionist` role gets and why. Change both printed passwords
immediately after first login.

## Conventions

- Layered architecture: `router → service → repository → model`. A repository never calls a service; a model never imports a schema.
- Every table follows the same standards: UUIDv7 primary keys, soft delete, server-generated timestamps only, audit-on-write.
- All endpoints return the standard response envelope: `{"data": ..., "meta": ..., "error": ...}`.
- Authorization is permission-code based (`require_permission("module:action")`), checked on every protected endpoint — never inferred from a role name.
- One-directional module dependency graph: `patients`/`visits`/`queue` are the base; `reception`/`consultation`/`vitals`/`billing` depend downward on those; `search`/`dashboard` are read-only on top.

## Running Tests

```bash
pip install -r requirements-dev.txt
pytest              # full suite
ruff check app/ tests/
black --check app/ tests/
```
