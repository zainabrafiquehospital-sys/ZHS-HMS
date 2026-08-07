# Gynecology HMS — Frontend

Next.js 15 (App Router, JavaScript-only) frontend for the Gynecology
HMS. See the [repository root README](../README.md) for the full
project overview, architecture, environment variables, and setup
instructions — this file covers frontend-specific structure and
conventions only.

## Structure

- `src/app` — Next.js App Router routes, split into `(auth)` (login) and `(dashboard)` (everything behind authentication) route groups.
- `src/core` — application bootstrapping: global providers (`AppProviders`), environment config, route/permission constants (`core/constants/access.js`, `routes.js`).
- `src/features` — one folder per feature (`auth`, `reception`, `consultation`, `vitals`, `billing`, `patients`, `visits`, `dashboard`), each owning its own `components/`, `hooks/`, `api/`, and `schemas/`.
- `src/shared` — reusable UI primitives (hand-rolled shadcn-style components), layout shells, and cross-feature hooks (e.g. `usePatientsForVisits`).
- `src/services/api` — the shared Axios instance (`httpClient.js`, with silent refresh-on-401) and the in-memory access-token store.
- `public/images` — static assets, including the hospital logo used on printed documents.

## Getting Started

```bash
cp .env.example .env.local
npm install
npm run dev
```

The app runs at http://localhost:3000.

## Conventions

- JavaScript only (`.js` / `.jsx`) — no TypeScript.
- Inline Tailwind utility classes only — no CSS Modules/SCSS/styled-components.
- All server data access goes through TanStack Query hooks backed by the shared Axios instance — components never call `fetch`/`axios` directly.
- All forms use React Hook Form + Zod resolvers.
- The access token lives in memory only (`tokenStore.js`) — never `localStorage`/`sessionStorage`. The refresh token is an httpOnly cookie the backend sets and reads directly; the frontend never sees its value.
- Route/navigation visibility is permission-driven (`core/constants/access.js`) — a module a user lacks permission for is removed from the sidebar and blocked at the route level (`RequirePermission`), not just visually hidden. The backend's own permission check remains the actual authorization boundary.

## Production Build

```bash
npm run build
npm run start
```

> **Security note:** the pinned `next@15.1.0` has several disclosed
> CVEs fixed in later 15.x releases (`npm audit` will show these).
> Plan a tested upgrade before/soon after a public deployment — see the
> root README's Production Notes.
