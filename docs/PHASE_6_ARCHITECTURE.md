# Phase 6 Architecture — Clinical Workflow, Billing, Attendance

**Version:** 1.1 (canonical, freeze baseline)
**Status:** FROZEN — architecture approved, no implementation yet
**Supersedes:** v1.0 (2026-08-06) — every v1.0 decision is preserved unchanged in this document; v1.1 only adds the enterprise-grade refinements in §18–§24 and the state-machine/versioning detail folded into §4, §5, §7, §9, §14.
**Depends on / does not modify:** Phase 0 (Engineering Foundation), Phase 0.5 (Database & Workflow Architecture), Phase 5 (Auth & RBAC — frozen)
**Scope of this document:** architecture only. No code, no API contracts, no database migrations, no ORM models, no task lists. Every module described here is unbuilt as of this freeze; this document is what future implementation phases must conform to.

## Revision History

- **v1.0 (2026-08-06):** first canonical Phase 6 document — flexible patient flow, Reception-centralized billing, Attendance module, module dependency graph, Auth freeze contract.
- **v1.1 (2026-08-06):** enterprise-grade refinement pass. Adds: Visit/Consultation/Invoice lifecycle state machines, permanent Queue Token, clinical versioning, an explicit soft-delete policy, a centralized Search service, a Central Print Service, notification priority levels, per-role Dashboard architecture, multi-branch-ready entity design, and an Emergency workflow. No v1.0 decision was removed, weakened, or redesigned — every addition attaches to the existing Visit-as-backbone model and one-directional dependency graph.

---

## 1. Purpose and Position in the Program

Phase 5 delivered Authentication & RBAC and was explicitly frozen by the user as a stable, locked platform. Phase 6 is the architecture for everything that runs a patient through the hospital on top of that platform: Reception, the flexible patient flow, Vitals, Doctor Consultation, Billing, Pharmacy, Shifts, Attendance, Reports, Dashboards, Notifications, Printing, Audit, Security integration, and performance posture.

This document is the **single source of truth for Phase 6**. It replaces any earlier informal description of these modules. Where it is silent, Phase 0 / Phase 0.5 (external, held by the user) remain authoritative for standards not covered here (ID strategy, locking strategy, coding standards, API envelope, etc.), consistent with the root `README.md`'s statement that those two documents are the source of truth for anything not covered in-repo.

Nothing in this document authorizes touching `backend/app/modules/auth/`. See §11.

---

## 2. Architectural Style (carried forward, unchanged)

- **Layered modular monolith.** One backend deployable, one frontend deployable, internally partitioned into feature modules. No module calls another module's internals directly — only through its public service interface (mirroring how Phase 5 exposes `service.py` as the seam other layers use).
- **Backend layering per module:** `router → service → repository → model`, each module living at `backend/app/modules/<feature>/`, exactly as Phase 5 does today (`auth/router.py`, `auth/service.py`, `auth/repository.py`, `auth/models.py`, plus the finer split Phase 5 uses for sub-resources like `user_router.py` / `role_router.py`). New Phase 6 modules (`reception/`, `vitals/`, `consultation/`, `billing/`, `pharmacy/`, `shifts/`, `attendance/`, `queue/`, `reports/`, `dashboard/`, `notifications/`) follow this same shape.
- **Frontend layering per feature:** `components/ hooks/ api/ schemas/` under `frontend/src/features/<feature>/`, server data only through TanStack Query + the shared `httpClient.js`, forms only through React Hook Form — same standard Phase 5's frontend counterpart would use.
- **Standard response envelope, UUID v7 primary keys, soft delete, server-generated timestamps, audit-on-write** — all standards already established for Phase 5 apply unchanged to every Phase 6 module.
- **One-directional module dependencies only.** A module may depend on a module "beneath" it in the graph in §12; it may never be depended on back. This is what keeps the freeze on Auth safe and keeps Billing centralization enforceable.

---

## 3. Core Domain Entities (conceptual)

These are described at the concept level — responsibilities and relationships, not schemas or fields.

| Entity | Owning module | Role |
|---|---|---|
| **Patient** | `patients` | Demographic/clinical identity, independent of any single visit. |
| **Visit** | `visits` | The aggregate root for one hospital encounter. Everything that happens to a patient on a given day hangs off their Visit: which procedure, which doctor, current queue location, current clinical stage, links to its Vitals records, its Consultation, its Billing Invoice. |
| **Queue Entry** | `queue` | Where a Visit is *right now* (Reception / Vitals / Doctor) and why. Owned separately from Visit so routing logic doesn't live inside the clinical aggregate. |
| **Vitals Record** | `vitals` | One set of captured vitals, scoped to either "all standard vitals" (Workflow A) or a specific requested subset (doctor mid-consult request). |
| **Consultation** | `consultation` (part of the Doctor module) | The doctor's active clinical session against a Visit. Holds its own status so it can pause and resume around a vitals detour. |
| **Pending Billing Item** | `billing` | A billable thing the doctor introduced mid-consultation (procedure, drug, service) that Reception has not yet reviewed. |
| **Invoice** | `billing` | The authoritative, Reception-owned financial record for a Visit. Only Billing/Reception can create or mutate it. |
| **Shift** | `shifts` | A named time window (e.g. Morning, Evening, Night) assignable to any staff role. |
| **Attendance Record** | `attendance` | One per staff member per calendar day (see §8.4 for the uniqueness rule), derived from login/logout activity and scored against the staff member's Shift. |
| **Notification** | `notifications` | A cross-cutting event delivered to a role's queue (e.g. Reception told a billing item is pending). |
| **Audit Log Entry** | shared/audit (cross-cutting) | Immutable record of who changed what, reused from the Phase 5-era standard, extended to cover every state transition introduced in this document. |

**v1.1 note:** Visit, Consultation, and Invoice each now have a full lifecycle state machine (§4.1, §5.4, §7.4). Every Visit carries a permanent Queue Token (§18). None of this changes ownership in the table above — it formalizes the states those owning modules already managed informally in v1.0.

---

## 4. The Visit as the Backbone of Phase 6

Every workflow in this document — flexible routing, doctor-initiated vitals, billing requests — is a state change on a **Visit**, never a parallel, disconnected process. This is the key structural decision that makes "pause consultation, go to vitals, come back to the same doctor" possible without ad-hoc coupling between Doctor and Vitals: both modules only ever act *through* the Visit and its Queue Entry, never directly on each other.

A Visit's clinical stage moves through: `Registered → (Vitals) → With Doctor → (Vitals, zero or more times) → With Doctor → Closed`. A Visit's queue location is a separate, faster-changing property that always answers "which role's worklist does this Visit currently sit in."

### 4.1 Visit Lifecycle State Machine (formalized in v1.1)

The informal stage description above is now a named state machine. It does not change the flow already approved in v1.0 — it gives each point in that flow an explicit status so "every module may only perform valid state transitions" is checkable rather than implicit:

- **Registered** — Reception has created the Visit (§6); initial routing decision made.
- **Waiting Vitals** — Queue Entry points at Vitals (Workflow A intake, or a doctor-initiated detour, §5.2).
- **Waiting Doctor** — Queue Entry points at Doctor; vitals (if any) are complete or were never required (Workflow B).
- **In Consultation** — a Doctor has an active Consultation open against this Visit (mirrors the Consultation's own `In Progress` / `Awaiting Vitals` sub-states, §5.4 — a Visit can be `In Consultation` while its nested Consultation is briefly `Awaiting Vitals` mid-detour; the Visit does not leave `In Consultation` for a doctor-initiated vitals detour, only its Queue Entry temporarily redirects).
- **Waiting Billing** — Consultation completed with billable items pending Reception review (§7).
- **Payment Pending** — Reception has an Invoice in `Pending Payment` or `Partially Paid` state against this Visit (§7.4).
- **Completed** — Invoice is `Paid` (or the Visit required no payment) and all clinical work is closed.
- **Cancelled** — Visit terminated before completion (no-show, registration error, etc.); never deleted (§20).

**Rule:** no module may write a Visit status that isn't a valid transition from its current status, and no module may move a Visit to a downstream status by bypassing the module that owns that transition (e.g., only Billing/Reception can move a Visit out of `Payment Pending`). This is the same one-directional-dependency discipline as §12, applied to state transitions rather than module calls.

---

## 5. Flexible Patient Flow

### 5.1 Two entry workflows, one decision point

Reception is the **only** place that decides whether a Visit needs Vitals before the doctor. This is captured once, at registration, as part of Visit creation — not inferred, not defaulted by any other module.

**Workflow A — Vitals required**
```
Reception → Vitals → Doctor
```

**Workflow B — Vitals not required**
```
Reception → Doctor
```
Used for follow-ups, medicine refills, report reviews, quick consultations — any case where Reception judges vitals unnecessary at intake.

Both workflows converge on the same downstream steps (Prescription / Billing / Pharmacy); they only differ in whether Vitals sits between Reception and the first Doctor touch.

### 5.2 Doctor-initiated vitals (mid-consultation)

A Doctor may, at any point in an active Consultation, decide additional vitals are needed (BP, sugar, weight, temperature, SpO₂, BMI, pulse, pregnancy vitals, etc.) — regardless of which workflow the Visit entered on. The Doctor's UI exposes a **"Send to Vitals"** action that:

1. Records a **targeted vitals request** against the Consultation (which specific vitals are needed, requested by which doctor).
2. Moves the Consultation into an **Awaiting Vitals** status. The Consultation is *paused*, not discarded — all clinical notes entered so far remain attached and resume exactly where they left off.
3. Re-routes the Visit's Queue Entry to Vitals, tagged as a targeted (not full) vitals request.

Vitals staff see only the requested vitals for that Visit — never a duplicate full workup. On completion:

4. The Vitals Record is attached to the Visit and to the originating Consultation.
5. The Queue Entry automatically routes the Visit back to **the same doctor** who requested it (not a general doctor queue) — continuity of care requires the returning patient land on the same clinician's worklist, not any available doctor.
6. The Consultation status returns to **In Progress**; the doctor resumes.

This produces the full dynamic path the business now requires:
```
Reception → Doctor → Vitals → Doctor → Prescription / Billing / Pharmacy
```
— which composes cleanly with Workflow A, since a Workflow-A Visit can *also* have a doctor-initiated detour later in the same encounter:
```
Reception → Vitals → Doctor → Vitals (doctor-requested) → Doctor → ...
```

### 5.3 Why this is a Queue concern, not a Doctor/Vitals coupling

The Doctor module never talks to the Vitals module directly, and Vitals never talks back to Doctor directly. Both only ever mutate the shared Visit/Queue Entry. This is what keeps the dependency graph acyclic (§12) and what makes "any number of vitals detours, always returning to the requesting doctor" fall out of the model for free rather than needing special-cased handoff code.

### 5.4 Consultation Lifecycle State Machine (new in v1.1)

The Consultation entity (§3) now has an explicit state machine, replacing the informal "In Progress / Awaiting Vitals" pairing used in v1.0 §5.2 with the full set:

- **In Progress** — doctor actively working the Consultation.
- **Awaiting Vitals** — paused for a doctor-initiated vitals detour (§5.2); the same status v1.0 already introduced, now formally enumerated here rather than only in §5.2.
- **Awaiting Lab** *(future-ready)* — reserved for when a Lab module exists; not implemented, but the status is architected now so Lab attaches the same way Vitals does (request → detour → automatic return to the same doctor), without a future redesign of this state machine.
- **Awaiting Radiology** *(future-ready)* — same reservation, for a future Radiology module.
- **Completed** — clinical work finished; see immutability rule below.
- **Cancelled** — Consultation terminated without completion (e.g., patient left); never deleted (§20).

**Rules:**
- A **Completed** Consultation cannot be edited in place.
- A **Clinical Addendum** is allowed after completion — an appended, separately timestamped and attributed note, not a rewrite of the original record.
- Every edit to Doctor Notes, Prescription, Diagnosis, or Clinical Assessment creates a new version rather than overwriting the previous one (full detail in §19, Clinical Versioning) — Consultation notes are never deleted, only superseded.
- This state machine composes with §4.1's Visit lifecycle without conflict: a Consultation moving to `Awaiting Vitals` does **not** move its parent Visit out of `In Consultation` — only the Queue Entry redirects, exactly as §5.2 already specified.

---

## 6. Reception Module

Reception is upgraded from "front desk" to the **sole workflow-initiation and sole financial authority** point of the system. Its responsibilities:

- **Patient registration** (create or pull up a Patient).
- **Visit creation** for today's encounter.
- **Procedure selection** (what the patient is here for).
- **Doctor selection** (which clinician the Visit is destined for).
- **Vitals-required decision** (Yes/No) — this single choice sets the Visit's initial queue destination:
  - Yes → Queue destination = Vitals
  - No → Queue destination = Doctor
- **All billing and payment collection** for the Visit, including revised invoices triggered by doctor billing requests (§7).
- **Printing** of registration slips and (revised) invoice slips.

No other module registers a Visit, decides its initial routing, or touches money. This module is intentionally the narrow neck through which both the clinical workflow and the financial workflow start.

---

## 7. Billing Architecture — Reception as Sole Financial Authority

This is a hard invariant, not a default: **Doctors never receive payments, never modify invoices, never edit prices.** The Doctor module has no capability, UI surface, or permission that touches money — this is enforced architecturally (the capability doesn't exist in the Doctor module's surface), not merely by an RBAC flag that could be miscon­figured later.

### 7.1 What a doctor can do about money

When a doctor performs or orders something billable mid-consultation (injection, nebulizer, drip, procedure, ultrasound, minor surgery, additional medicine, etc.), the only action available is: **submit an additional charge request.** This creates a **Pending Billing Item** against the Visit — a clinical fact ("this was done / ordered"), not a financial transaction.

### 7.2 What happens next (always Reception-owned)

1. Pending Billing Item is created, linked to the Visit and the requesting doctor.
2. A Notification is raised to Reception's queue (§9).
3. Reception reviews the pending item(s).
4. Reception (via the Billing module) recalculates/updates the Visit's Invoice.
5. Reception prints a revised slip.
6. Reception collects the payment.

Billing is therefore always centralized in one module (`billing`), always executed by Reception, regardless of how many doctor-originated charge requests accumulate against a Visit during its lifecycle. Pharmacy dispensing (§7.3) follows the identical pattern — it never collects payment itself either.

### 7.3 Pharmacy's relationship to Billing

Pharmacy dispenses against a Prescription produced by Consultation. Any dispensed item that carries a charge becomes a Pending Billing Item through the same mechanism as §7.1–7.2 — Pharmacy does not open a second, parallel payment channel. This keeps "Reception is the only payment collection point" true system-wide, not just for doctor-originated charges.

### 7.4 Invoice Lifecycle State Machine (new in v1.1)

The Invoice entity (§3) now has an explicit state machine layered on top of the §7.1–§7.3 pipeline, which is otherwise unchanged:

- **Draft** — Invoice assembled from the Visit's procedure + accumulated approved billing items, not yet presented for payment.
- **Pending Payment** — presented to the patient at Reception, no payment recorded yet.
- **Partially Paid** — some but not all of the Invoice total has been collected.
- **Paid** — fully settled.
- **Cancelled** — voided before payment (e.g., visit cancelled).
- **Refunded** *(future-ready)* — reserved for a future refund workflow; not implemented now, but the state exists so refunds attach to this same machine later rather than requiring a redesign.

**Rules (all reinforce, never loosen, §7's Reception-only invariant):**
- **Paid invoices are immutable.** Once an Invoice reaches `Paid`, its line items, totals, and status never change again.
- **Doctors can never modify invoices** — unchanged from §7; this rule restates it against the new state machine explicitly so no state (including `Draft`) is ever doctor-writable.
- **Reception is the only role allowed to update an Invoice, and only before payment** — i.e., while it is `Draft` or `Pending Payment`/`Partially Paid` for the purpose of recording payment progress. Reception has no capability to edit a `Paid` Invoice, either.
- **A billing request that arrives after payment never reopens the paid Invoice.** If a doctor submits a new Pending Billing Item against a Visit whose current Invoice is already `Paid`, Billing creates a **new, separate Outstanding Invoice** for that Visit (starting at `Draft`/`Pending Payment`) instead of mutating the locked one. A Visit may therefore accumulate more than one Invoice over its lifetime, each independently immutable once `Paid` — this is intentional and is what "the original invoice remains locked" means architecturally.
- **Every Invoice revision is fully audit-logged** — creation, each line-item change while mutable, and every status transition, per §15 (Audit), with no exception carved out for this entity.

---

## 8. Attendance Module (new)

### 8.1 Classification

Attendance is **infrastructure that observes Auth, not a clinical or workflow module**, and it is **not part of Auth**. It has its own module directory (`backend/app/modules/attendance/`) and its own frontend feature, and it depends on Auth — Auth never depends on it. See §11 for how this dependency is kept one-directional without touching frozen Phase 5 files.

### 8.2 Behavior

- Successful login → **automatic Check-In**.
- Logout → **automatic Check-Out**.
- Unexpected disconnect (browser closed without logout) → the session is checked out automatically once a **configurable inactivity timeout** elapses; until then, or as an alternative, an Admin may manually check the user out.
- Applies to every role that authenticates through the frozen Auth platform where attendance tracking is desired for that role (Reception, Doctors, Vitals staff, Nurses, Lab, Radiology, Pharmacy) — the scope is a configuration of *which roles are tracked*, not a structural difference in how tracking works.

### 8.3 Record contents (conceptual)

Each Attendance Record conceptually captures: staff identity, date, check-in time, check-out time, computed working hours, assigned Shift, late-arrival flag, early-checkout flag, overtime, and optionally device/IP metadata. All of these are *derived or flagged* against the staff member's Shift definition (§10) — Attendance never defines its own notion of "late" independent of Shift.

### 8.4 No duplicate attendance per day

An Attendance Record is unique per (staff member, calendar date). Multiple login/logout cycles within the same day update that single day's record (earliest check-in kept, latest check-out kept, session time accumulated for working-hours/overtime) rather than producing multiple records. This uniqueness is an architectural invariant the Attendance module enforces, independent of how many times a staff member authenticates in a day.

### 8.5 Visibility

Attendance records and the Attendance Dashboard (§8.6) are visible **only to Admin and HR** roles, enforced through the existing (frozen) RBAC permission model exactly as any other protected resource is — Attendance introduces no new authorization mechanism, it consumes the one Phase 5 already provides.

### 8.6 Attendance Dashboard

Admin/HR-only view providing: today's attendance, present staff, absent staff, currently-online staff, late arrivals, overtime, early checkouts, monthly attendance, shift reports, attendance history, and export to Excel and PDF.

---

## 9. Notifications Architecture

A lightweight, in-process, cross-cutting notification mechanism (no external message broker — consistent with the modular-monolith style) delivers role-scoped events, for example:

- Doctor requests vitals → Vitals role queue notified.
- Vitals completes a targeted request → originating Doctor notified.
- Doctor submits a Pending Billing Item → Reception notified.
- Reception finalizes a revised invoice → (optionally) Doctor notified the request was processed.

Notifications are a *delivery* concern layered on top of the Visit/Queue/Billing state changes described above — they do not carry business logic themselves, and no module's correctness depends on a notification being delivered (routing and billing state changes happen regardless; notifications are advisory).

### 9.1 Notification Priorities (new in v1.1)

Every Notification carries a severity, still purely a delivery/presentation concern (§9's "advisory, not business logic" rule is unchanged):

- **Critical** — e.g. an Emergency patient registered (§24).
- **High** — e.g. Doctor Requested Vitals (§5.2).
- **Normal** — e.g. Pending Billing item raised (§7.1).
- **Low** — e.g. a routine system reminder.

Priority affects how a notification is surfaced to its recipient role (ordering, visual weight, whether it interrupts) — it does not change *whether* or *to whom* it is delivered, which remains governed by the event-driven producer/consumer pairing already described above.

---

## 10. Shift Module and Integration

Shift is a shared definition module (`shifts`) used identically by every role that needs one: Reception, Doctors, Vitals, Nurses, Lab, Radiology, Pharmacy. A Shift defines a named working window (start, end, grace period for lateness, expected overtime threshold).

Every Attendance Record belongs to exactly one Shift (the staff member's assigned shift for that date), and it is the Shift definition — not Attendance itself — that supplies the boundaries used to compute late-arrival, early-checkout, and overtime flags. This keeps "what counts as late" a single, centrally-defined fact rather than something each module could interpret differently.

---

## 11. Auth Freeze — How Attendance Integrates Without Touching Auth

This section exists specifically to satisfy the non-negotiable constraint: **Phase 5 is not redesigned, refactored, moved, or rewritten.**

Attendance integrates purely as an **external observer of Auth's already-existing login/logout outcomes**:

- Attendance's own module (`attendance/`) sits outside `auth/` entirely and depends on Auth only through Auth's existing public login/logout service interface — the same interface every other consumer of Auth already uses. No file inside `backend/app/modules/auth/` is read for modification, edited, or reorganized by this document or by anything it authorizes.
- The integration point is an **event/observer boundary**: when Auth's login use-case completes successfully, and separately when Auth's logout use-case completes, Attendance reacts to that outcome (conceptually, "listens for" it) and performs its own check-in/check-out write inside its own module. This is a consumer relationship, not a modification of the producer.
- Because this is strictly one-directional (`attendance → auth`, never `auth → attendance`), Auth's frozen code has zero awareness of Attendance's existence. Auth cannot break because Attendance changes, and freezing Phase 5 places no constraint on how Attendance evolves.

This is the only sanctioned relationship between the two modules. Any future design that requires Auth itself to change in order to support Attendance (or anything else) is out of scope for this document and would require an explicit, separate unfreezing decision — which this document does not make.

---

## 12. Module Dependency Graph (no cycles)

Dependencies read "depends on, calls into." Nothing on the right depends back on anything to its left.

```
auth (frozen)
  ← attendance            (observes login/logout outcomes only, §11)
  ← every other module     (identity + permission checks, unchanged Phase 5 pattern)

shifts
  ← attendance             (record scored against a shift)

patients, visits, queue
  ← reception               (creates/updates Visit + Queue Entry)
  ← vitals                  (reads Visit, writes Vitals Record, updates Queue Entry)
  ← consultation (doctor)   (reads Visit, writes Consultation, updates Queue Entry)
  ← billing                 (reads Visit, writes Invoice / Pending Billing Items)
  ← pharmacy                (reads Visit/Prescription, writes dispense record + billing items)

billing
  ← pharmacy                (routes dispensed charges through Billing, §7.3)
  ← consultation (doctor)   (submits Pending Billing Items only — never writes Invoice directly)

notifications (cross-cutting; published to, not owned by, any workflow module)
  ← reception, vitals, consultation, billing   (all may publish/consume)

reports, dashboard
  ← read-only aggregation across visits, queue, billing, attendance, shifts
    (reporting modules depend on everything they report on; nothing depends back on them)
```

**Consequence:** Doctor (`consultation`) can reach `billing` only through the one-way Pending-Billing-Item submission path — it has no dependency edge onto Invoice mutation, which is the structural enforcement behind "doctors never modify invoices," not just a permission check.

### 12.1 v1.1 additions to the graph

Every new v1.1 concept attaches to the existing graph shape below without introducing a cycle:

```
search (cross-cutting, read-only; §18)
  ← consumed by reception, vitals, consultation, billing, attendance, reports, dashboard
    (search reads across visits/queue/billing/patients/attendance; nothing depends back on it)

print (cross-cutting service; §14)
  ← consumed by reception, consultation, pharmacy, billing
    (each hands print a document to render; print never calls back into the requesting module)

dashboard (was already read-only in v1.0; §22 makes its per-role split explicit)
  ← still read-only aggregation across visits, queue, billing, attendance, shifts — unchanged edge direction
```

`queue`'s Queue Token (§18) and Emergency priority flag (§24) are **attributes on the existing `queue`/`visits` modules**, not new modules — they add no new edges to the graph. Multi-branch readiness (§20) is likewise a conceptual attribute carried by every entity already in this graph, not a new module or edge. This is why none of §18–§24 required renegotiating §12's original shape.

---

## 13. Security

- All authorization continues to run through the frozen Phase 5 RBAC model — Phase 6 modules define their own permissions the same way Phase 5's own resources do (per-module permission set, resolved through the existing effective-permission resolution), and register those permissions as consumers, not by altering how RBAC itself works.
- Segregation of financial duties is enforced at two levels simultaneously: (a) RBAC — a Doctor role is never granted billing-mutation permissions; (b) module surface — the Doctor module has no billing-mutation capability to grant permission to in the first place (§7, §12). This double enforcement is intentional: a future permission misconfiguration still cannot let a doctor mutate an invoice, because the code path doesn't exist in that module.
- Attendance/Shift visibility (Admin/HR only) is an ordinary RBAC-protected resource, no special-cased mechanism.

---

## 14. Printing — Central Print Service (expanded in v1.1)

Printing remains a Reception-owned output for anything financial (registration slip, invoice slip, revised invoice slip after a billing update) and a Doctor/Pharmacy-owned output for anything clinical (prescription, dispense note). No module prints a document type it does not own the data for — Doctor cannot print an invoice; Reception does not print prescriptions. That ownership rule is unchanged.

**v1.1 refinement:** printing itself becomes a shared infrastructure service (`print`, §12.1) rather than each module implementing its own rendering. Every printable document — Registration Slip, Invoice, Updated Invoice, Prescription, Medical Certificate, and (future) Discharge Summary — passes through this one Print Service, which is responsible for layout/rendering, not for deciding *whether* a module may print a given document (that authorization still belongs to the owning module, per the paragraph above).

Supported output today: **PDF**, **thermal printer**, **A4 printer**. Reserved for future, without requiring a redesign of the service boundary: **WhatsApp** and **email** delivery of the same rendered documents.

---

## 15. Audit

The audit-on-write standard already established for Phase 5 extends to every state transition introduced in this document, at minimum: Visit creation and stage transitions, Queue Entry routing changes (including doctor-initiated vitals detours), Pending Billing Item creation and Invoice revision, Attendance manual overrides by Admin, and Shift reassignments. No new audit mechanism is introduced — this is the same immutable, who/what/when record already standard, applied to a wider set of write paths.

---

## 16. Performance Considerations

- Queue Entry lookups (per role worklist) and Attendance "currently online" queries are the two highest-frequency reads in this design and should be served from indexed, current-state tables rather than derived by scanning history each time.
- Attendance Dashboard aggregates (today's present/absent/late/overtime, monthly rollups) are read-heavy, Admin/HR-only, and tolerate slight staleness — architected as pre-aggregatable rather than always computed live across raw check-in/out events.
- Billing recalculation on a Pending Billing Item approval touches a single Visit's Invoice — no cross-Visit locking is required, keeping Reception's revision step cheap even under concurrent multi-counter use.
- These follow the same async SQLAlchemy / Redis-caching posture already standard for the platform; this section states where Phase 6 specifically stresses that posture, it does not introduce a new performance standard.

---

## 17. Extensibility Considerations

The Visit-as-backbone model (§4) and the one-way module graph (§12) are what let future modules (Admission, Discharge, Lab, Radiology, Reports, Dashboard, Settings, Audit Logs — all still listed as unbuilt) attach without redesign: each new module becomes another consumer of Visit/Queue, another optional producer of Pending Billing Items if it introduces billable actions, and another optional Attendance-tracked role if its staff authenticate through Auth. None of those future additions require reopening this document's core decisions, only extending the dependency graph downward from `visits`/`queue`/`billing`.

---

## 18. Queue Architecture and Token (new in v1.1)

Every Visit receives a **permanent Queue Token** at registration (e.g. `GYN-0001`, `OBS-0010`, `ANC-0005` — prefix by department/procedure type, sequential number).

- **The token never changes** for the life of the Visit, regardless of how many times the Visit moves between Reception, Vitals, and Doctor (§5), or how many Invoices it accumulates (§7.4).
- **Queue position may change** — a Visit's place in a given role's worklist is expected to move (priority, re-ordering, emergency insertion per §24); this is independent of the token.
- **Queue history is preserved** — every routing change a Visit's Queue Entry goes through (§5.3, §12) is retained, not overwritten, so the full path a Visit took through the hospital can always be reconstructed against its one, unchanging token.

The token is what patients, Reception, and printed slips (§14) reference; internal routing state (current destination, priority) is a separate, mutable property of the same Queue Entry, exactly as `Queue Entry` was already scoped in §3.

---

## 19. Clinical Versioning (new in v1.1)

Doctor Notes, Prescription, Diagnosis, and Clinical Assessment — all part of the Consultation entity (§3, §5.4) — are versioned, never overwritten:

- Every edit creates a new revision; the prior revision remains readable, not deleted.
- This applies both while a Consultation is `In Progress` (successive edits during the same visit) and after `Completed`, where only a Clinical Addendum (§5.4) — itself a new, appended revision — is permitted.
- A complete audit trail (who changed what, when, from which revision to which) is required for every one of these fields, using the same audit standard as §15, extended to carry revision lineage rather than just before/after state.

This is what makes §5.4's "Completed consultations cannot be edited" rule safe in practice: nothing is ever lost, because nothing is ever overwritten — history accumulates instead of being replaced.

---

## 20. Soft Delete Policy (new in v1.1)

The platform-wide soft-delete standard already listed in §2 is now explicitly enumerated for the entities where accidental or malicious permanent loss would be most damaging: **Patients, Visits, Invoices, Consultations, Prescriptions, Vitals**. None of these is ever permanently deleted by any module — only archived or deactivated. Recovery must remain possible for all of them. This is a restatement and explicit scoping of the existing §2 standard, not a new mechanism.

---

## 21. Global Search Architecture (new in v1.1)

A centralized search service, reusable by every module (§12.1), supports lookup by: **MR Number, Visit ID, Queue Token (§18), Patient Name, CNIC, Phone Number.**

Search is read-only and cross-cutting — it depends on `patients`, `visits`, `queue`, and (where a module grants it visibility) `billing`/`attendance`, but nothing depends on Search, so it introduces no cycle (§12.1). Any module needing to locate a patient, visit, or queue token uses this one service rather than implementing its own lookup logic — the same "one canonical path" discipline already applied to Billing (§7) and Printing (§14).

---

## 22. Dashboard Architecture (new in v1.1)

Dashboards are split by role rather than being one general-purpose screen:

- **Reception Dashboard**
- **Doctor Dashboard**
- **Vitals Dashboard**
- **HR Dashboard**
- **Admin Dashboard**
- **Owner Dashboard**

Each dashboard is a read-only aggregation (consistent with `dashboard`'s existing edge direction in §12) and **displays only the data its viewer's RBAC permissions allow** — the same double enforcement pattern already used for billing segregation (§13): a role without permission to see billing data cannot see it on their dashboard, because the dashboard's queries are scoped by the same effective-permission resolution as everywhere else, not by a separate dashboard-specific rule. The Admin/HR-only Attendance Dashboard (§8.6) is one instance of this pattern, not a special case.

---

## 23. Multi-Branch Ready Architecture (new in v1.1)

Without changing current single-branch behavior, every major entity is made **conceptually branch-aware**: Patient, Visit, Queue, Billing, Attendance, Shift, Reports, Dashboard. Each of these entities is understood to conceptually carry a branch reference, so that a future multi-hospital deployment attaches to the existing model rather than requiring it to be redesigned.

- **Today:** single branch; the branch dimension is not exposed, enforced, or exercised anywhere.
- **Future:** the same entities, the same one-directional dependency graph (§12), and the same RBAC/module boundaries extend to multiple branches by scoping queries and permissions along the branch dimension already latent in the model.

This section authorizes no branch-specific behavior now — it only obligates future entity design (when it is eventually implemented) to treat branch as a first-class dimension of these entities rather than bolting it on.

---

## 24. Emergency Workflow (new in v1.1)

Emergency Visits get a dedicated priority path, not a separate parallel system:

```
Reception
  ↓
Emergency Priority
  ↓
Doctor
  ↓
Vitals (if required)
  ↓
Admission
```

- Reception still creates the Visit (§6) — an Emergency Visit is a Visit, using the same aggregate (§4), same Queue Entry mechanism (§5.3), and same Queue Token (§18) as any other. What differs is a priority flag that lets it **bypass the normal queue order**.
- Vitals is still governed by the same flexible-flow decision as §5.1 — an Emergency Visit may go straight to Doctor or through Vitals first, at Reception's judgement, exactly as the non-emergency flow already supports both shapes.
- "Admission" as the terminal step in this diagram is a forward reference to a not-yet-designed Admission module (already listed as future scope in §17/Extensibility); this document does not design Admission, it only confirms the Emergency path terminates by handing off to it rather than to standard Billing/Pharmacy closure.
- Because priority is a property of the Queue Entry (§18) and not a new module or a new dependency edge, this composes with §12's graph exactly as Queue Token and Multi-Branch readiness do (§12.1) — no cycle, no new coupling between Reception/Vitals/Doctor beyond what §5.3 already establishes.

---

## 25. Updated Implementation Roadmap

This sequencing reflects where Attendance and the flexible-flow decisions land relative to already-frozen Phase 5, without violating the freeze:

1. **Visit / Queue foundation** — the shared aggregate and routing entity everything else attaches to (§4, §12). Built first because Reception, Vitals, Doctor, and Billing all depend on it and it depends on nothing new.
2. **Reception** — registration, Visit creation, the Vitals-required decision, initial routing (§6).
3. **Vitals** — full-workup handling (Workflow A) and targeted-request handling (doctor-initiated detour), sharing one module (§5).
4. **Doctor / Consultation** — clinical workflow, "Send to Vitals," Pending Billing Item submission (§5.2, §7.1).
5. **Billing** — Invoice, Pending Billing Item review/approval, revised-slip printing (§7.2).
6. **Shifts** — introduced before Attendance since Attendance records score against Shift definitions (§10).
7. **Attendance** — built as the observer module described in §11, strictly after Shifts exists and without touching `auth/`.
8. **Pharmacy** — dispensing against Prescription, billing items via the same Pending Billing Item path (§7.3).
9. **Notifications** — cross-cutting delivery layer, introduced incrementally alongside 2–8 as each producer/consumer pair goes live (§9).
10. **Reports / Dashboard(s)** — including the Admin/HR Attendance Dashboard (§8.6), built last since they are read-only aggregations over everything above.

Phase 5 (Auth/RBAC) requires no roadmap entry — it is already complete and frozen; step 7 is the only step that touches its boundary, and only as a downstream consumer.

**v1.1 note (roadmap unchanged, only annotated):** every §18–§24 addition refines an existing stage rather than inserting a new one — Queue Token (§18) and the Visit/Consultation/Invoice state machines refine stage 1/4/5; Clinical Versioning (§19) and Soft Delete (§20) refine stages 4 and (system-wide) all stages; the Central Print Service (§14) refines stages 2/4/5/8 wherever printing already occurred; Notification Priorities (§9.1) refine stage 9; Search (§21), Dashboard (§22), and the Attendance Dashboard's siblings refine stage 10; Multi-Branch readiness (§23) is a design obligation on every stage, not a stage of its own; Emergency (§24) refines stages 1–2. The ten stages and their sequencing are otherwise exactly as approved in v1.0.

---

## 26. Final Self-Review

**v1.0 checks (unchanged, still hold under v1.1):**

- **Circular dependencies:** none. §12's graph is acyclic; `auth` and `shifts` sit at the base with nothing depending back on them incorrectly, `visits`/`queue` are the shared middle layer, workflow modules (`reception`, `vitals`, `consultation`, `billing`, `pharmacy`) depend downward only, and `reports`/`dashboard`/`notifications` are read-only or cross-cutting with no one depending on them.
- **Billing inconsistency:** none. Every billable path (doctor mid-consult charge, pharmacy dispense) converges on the single Pending-Billing-Item → Reception-review → Invoice-update pipeline (§7). There is exactly one Invoice-mutation path in the entire system, and it is owned by Billing, executed by Reception.
- **Doctor never handles payments:** structurally enforced — no Doctor-module dependency edge reaches Invoice mutation (§12), reinforced by RBAC (§13).
- **Reception remains the single financial authority:** Reception is the only role with a dependency edge into Invoice mutation and the only module that prints financial slips (§6, §14).
- **Workflow ambiguity:** none — both routing paths reduce to one primitive (Queue Entry destination on the shared Visit, §4–§5.3), so Workflow A, Workflow B, and any number of doctor-initiated vitals detours are the same mechanism applied repeatedly, not three separate code paths.
- **Vitals routing supports both required flows:**
  - `Reception → Vitals → Doctor` — Workflow A, §5.1.
  - `Reception → Doctor → Vitals → Doctor` — Workflow B plus a doctor-initiated detour, §5.1–§5.2. Confirmed supported, including the always-returns-to-the-requesting-doctor guarantee (§5.2 step 5).
- **Auth freeze:** confirmed intact — §11 is the entire contract; no other section reaches into `auth/`.

**v1.1 checks (new):**

- **Layer violations:** none. Every new capability (Search §21, Print §14, Dashboard §22) is either a cross-cutting read-only/render service consumed one-directionally by existing modules, or an attribute (Queue Token §18, priority §24, branch §23) on an entity that already existed in §3/§12 — no new module was given write access to another module's aggregate.
- **Workflow conflicts:** none. The Visit (§4.1), Consultation (§5.4), and Invoice (§7.4) state machines were checked pairwise: a Consultation's `Awaiting Vitals` sub-state does not force its parent Visit out of `In Consultation` (§4.1), and an Invoice moving to a new Outstanding Invoice after a `Paid` lock (§7.4) does not require or imply any Visit-status regression — a Visit can be `Completed` with one `Paid` Invoice and still legitimately gain a second `Draft` Invoice from a later-approved billing item, without contradiction.
- **Billing inconsistencies:** none, and now stronger than v1.0 — §7.4's immutable-`Paid`/new-Outstanding-Invoice rule closes the one gap v1.0 left implicit (what happens to a post-payment billing request), without adding a second mutation path.
- **Queue inconsistencies:** none. The Queue Token (§18) is permanent and separate from queue position/priority, so Emergency re-ordering (§24) never risks token collision or loss of queue history.
- **Visit lifecycle conflicts:** none — §4.1's eight statuses are a strict refinement of v1.0's already-approved informal stage list; nothing in v1.0's flow description falls outside the new enum.
- **Consultation lifecycle conflicts:** none — §5.4 is additive to v1.0 §5.2, using the same `Awaiting Vitals` status name v1.0 already coined, plus two future-reserved statuses (`Awaiting Lab`/`Awaiting Radiology`) that no current module reads or writes.
- **Attendance conflicts:** none — §8 is untouched by this revision; Shift-scoring (§10) and the Auth-observer boundary (§11) are unaffected by any v1.1 addition.
- **Branch conflicts:** none — §23 is deliberately non-operative today (single-branch behavior unchanged); it constrains future design, not current architecture.
- **Future scalability:** confirmed — Lab/Radiology attach to §5.4 the same way Vitals already does; Admission attaches to §24's Emergency terminus and to the general Visit lifecycle (§4.1) the same way Discharge will; multi-branch (§23) and Refunded invoices (§7.4) are both reserved, not designed, so neither blocks anything already approved.

---

## 27. Freeze Declaration

This document, **Phase 6 Architecture v1.1**, is the approved and frozen architecture for the flexible patient flow, Reception-centralized billing, the Attendance module, and the v1.1 enterprise refinements (lifecycle state machines, Queue Token, clinical versioning, soft-delete policy, centralized Search, Central Print Service, notification priorities, per-role Dashboards, multi-branch readiness, and the Emergency workflow). It supersedes v1.0 by extension only — every v1.0 decision remains intact and is restated or cross-referenced throughout this document, none removed or weakened.

It governs implementation of: `reception`, `vitals`, `consultation` (Doctor), `billing`, `pharmacy`, `shifts`, `attendance`, `queue`, `visits`, `notifications`, `reports`, `dashboard`, plus the v1.1 cross-cutting services `search` and `print`. Phase 5 (`auth`) remains separately frozen and unmodified by anything in this document. No implementation work is authorized by this document alone — it defines what any future implementation phase must conform to.
