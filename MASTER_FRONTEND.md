# MASTER_FRONTEND.md
### EduFlow AI — Frontend & UX Architecture
**Document Type:** Frontend Architecture — Single Source of Truth
**Inherits from:** MASTER_PRODUCT, MASTER_ARCHITECTURE, MASTER_BACKEND
**Version:** 1.0

---

## 0. Purpose

This document defines **how the user-facing experience is built**: the client application architecture, the per-persona experiences over one platform, the tenant-vocabulary label system, progressive disclosure, the offline-first consumption clients, the provenance ("why this value?") UI, and the timetable interaction surfaces. It governs *structure and UX principles*, not pixel-level design (which follows the frontend-design skill/tokens at build time).

The frontend's prime directive, from `MASTER_PRODUCT`: **the same platform must feel native to a government-school clerk, a university registrar, a coaching-centre owner, a teacher, and a parent** — through configuration, not code forks.

---

## 1. Frontend Architectural Drivers

The highest-leverage requirements from upstream docs:

1. **Progressive disclosure** (Principle #8) → a role/complexity-aware UI shell that reveals capability on demand.
2. **Tenant vocabulary** (`MASTER_PRODUCT §5` challenge) → the UI *never* shows abstract primitives; it renders the tenant's own words ("Batch"/"Section").
3. **Offline-first consumption** (`ARCHITECTURE ADR-006`) → local-first clients with sync and intent-writes.
4. **Explainability / provenance** (Principle #7) → "why this value?" and "why this timetable?" are UI surfaces, not hidden APIs.
5. **Localization structural** (Principle #9) → language, script, direction (RTL), calendar, formats are first-class.
6. **Low-bandwidth reality** → aggregation-friendly reads (GraphQL), small payloads, resilient retries.
7. **Real-time** → live solve progress and "timetable changed" push.

---

## 2. Application Topology

### ADR-FE-001 — Multiple client surfaces from a shared design system & shared domain layer

**Decision.** Three primary surfaces, one shared foundation:

| Surface | Users | Nature |
|---|---|---|
| **Admin / Console web app** | Super-admin, tenant admin, coordinator, HOD | Rich, capability-dense, desktop-first (but responsive) |
| **Consumption apps** (mobile-first web / native-shell) | Teacher, student, parent | Light, offline-first, glanceable |
| **Public/embed views** | Auditors, kiosk displays, shared timetable links | Read-only, brandable |

All share: a **design system** (tokens, components, accessibility, i18n), a **domain/data layer** (API clients, caching, sync), and the **label/vocabulary system** (§4).

**Rationale.** An admin console and a parent's "what's today" app have opposite constraints (dense vs. glanceable; online-authoring vs. offline-consuming). Forcing one app to do both yields a bad experience for everyone. Sharing the foundation avoids duplication and keeps behavior consistent. ❌ *One monolithic SPA for all personas* rejected (bloated, bad on low-end phones, poor offline). ❌ *Fully separate stacks* rejected (duplicated logic, drift).

### 2.1 Technology criteria (per MASTER_ARCHITECTURE §9)
Component-driven framework with: strong TypeScript support, first-class i18n & RTL, robust **service-worker/local-store** offline capability, accessibility maturity, and a healthy component ecosystem. The **frontend-design** skill governs visual token/styling decisions at implementation time.

---

## 3. Progressive Disclosure Shell

Realizes Principle #8. The UI **adapts to the actor's role, the tenant's enabled features, and complexity tier** — driven by the same **effective configuration** the backend resolves (`MASTER_BACKEND §3.3`).

- **Role-aware navigation:** a clerk never sees credit-hour configuration; a registrar can reach it. Navigation is generated from the actor's capabilities (data-driven, `MASTER_DATABASE §2.2`).
- **Complexity tiers:** "Simple mode" (guided, few options — govt/coaching) vs. "Advanced mode" (full constraint editing — universities). The tier is tenant config; users can request "show advanced."
- **Setup wizard** for onboarding (`MASTER_PRODUCT §7.1`): pack selection → guided hierarchy/calendar/subjects → first timetable, targeting **<1 day to first timetable**.

### ADR-FE-002 — The UI is generated from effective configuration + capabilities, not hard-coded per segment
**Rationale.** If the frontend hard-coded "CBSE screens," we'd fork per segment (violates Principle #1). Instead, screens are assembled from configured entities, custom fields, labels, and the actor's capabilities. ❌ *Segment-specific UI builds* rejected.

---

## 4. The Tenant Vocabulary (Label) System

The single most important UX mandate: **abstraction lives in the engine; the user sees their own words.**

- Every domain primitive has a **tenant label mapping** (config): `learner_group` → "Section" (CBSE) / "Batch" (coaching) / "Course-Section" (college). `resource_type` → "Teacher"/"Faculty"/"Instructor".
- The label layer is applied at render time everywhere — navigation, forms, reports, notifications, errors.
- **Localization composes with vocabulary:** the label is *then* translated into the user's language/script.

### ADR-FE-003 — A single label-resolution layer wraps all rendered domain terms
**Rationale.** Consistency and one place to change. A missed label = the user sees "Learner-Group," which breaks trust and the product promise (`MASTER_PRODUCT §5` challenge). ❌ *Per-screen hard-coded strings* rejected (drift, leaks, un-translatable).

---

## 5. The Timetable Experience (flagship surface)

The timetable is where the product is felt. UX requirements:

### 5.1 Generation & review (coordinator)
- **Constraint editor:** compose rules from the vocabulary in near-natural language, with the **AI assist** (`MASTER_AI`) offering to translate typed rules into constraints — always shown for confirmation, never applied silently.
- **Live lint feedback:** the constraint linter's problems (`MASTER_SCHEDULER §4.3`) surface *before* generation ("you need 8 Maths sessions but only 6 slots").
- **Generation with live progress:** streamed progress + intermediate solutions (real-time push).
- **Candidate comparison:** multiple solutions shown side-by-side with their trade-offs ("A minimizes teacher gaps; B maximizes room stability").
- **Conflict explanation:** on failure, the **Minimal Conflicting Set** is rendered as a fixable, human-readable list with one-click "relax this rule."

### 5.2 Manual editing with live validation
- Drag-and-drop / direct edit of assignments; **every edit is validated instantly** (`MASTER_SCHEDULER §7`), violations shown inline in real time (in-memory check, <100ms — no server round-trip for validation feedback).
- Manual placements become **locked pins** (respected by re-solves); the UI marks them clearly.

### 5.3 Consumption views (all personas)
- **Class / teacher / room / student / exam** views, each persona seeing their relevant slice.
- **Export & share:** PDF, print-optimized layouts, calendar feed subscription, shareable read-only links.
- **Change highlighting:** when a substitution/change occurs, the affected slot is visibly flagged and pushed.

### 5.4 "Why is this here?"
Any assignment can be interrogated → the engine's explanation chain (`MASTER_SCHEDULER §4.5`) is rendered ("Physics is here because rule X pinned mornings and the lab is free"). Trust through transparency.

---

## 6. Provenance UI ("Why this value?")

Realizes Principle #7 for configuration. On any effective setting, the user can reveal the **provenance trace** (`MASTER_BACKEND §3.1`): which layer (pack/tenant/campus/…) set the value, and whether a lock prevents override. This makes the 7-layer stack (`MASTER_PRODUCT §4.1`) **debuggable by the admin**, not just the engineer — directly mitigating the "undebuggable stack" risk.

---

## 7. Offline-First Consumption Clients

Realizes `MASTER_ARCHITECTURE ADR-006` and `MASTER_BACKEND §7`.

- **Local replica** of the user's scoped dataset (my timetable, my groups, today's changes) via service-worker + local store.
- **Works fully offline** for reads; shows a clear "last synced" indicator.
- **Intent-based writes** (accept swap, request leave) are **queued locally** and replayed on reconnect; the UI communicates pending/accepted/rejected clearly (the server may reject with a reason).
- **Delta sync** on reconnect (`MASTER_BACKEND §7`) minimizes bandwidth.
- **No offline authoring of schedules/config** — those are online operations; the UI makes this boundary clear rather than failing mysteriously.

### ADR-FE-004 — Consumption is local-first; authoring is online-only, and the UI states which mode it's in
**Rationale.** Prevents the dangerous illusion that offline edits to a schedule are authoritative (they can't be — constraints live server-side). Clear mode communication avoids user confusion and data-loss anxiety. ❌ *Silent offline everywhere* rejected (violates single-source-of-truth, risks corrupt schedules).

---

## 8. Localization & Accessibility (structural)

- **Language, script, direction (LTR/RTL), calendar, number/date/time formats** are resolved per user locale (`MASTER_PRODUCT` Principle #9) and **compose with tenant vocabulary** (§4).
- **Regional/academic calendars** render natively (the calendar is pluggable, `MASTER_ARCHITECTURE §8.2`).
- **Accessibility is a requirement, not a nice-to-have:** keyboard navigation, screen-reader semantics, sufficient contrast, and low-literacy-friendly patterns (icons + words) for the government segment. WCAG-aligned.
- **Low-end device performance** is a first-class target (the parent on a ₹6,000 phone must have a smooth "today" view).

---

## 9. Client Data & State Architecture

- **Server state** (from APIs) is cached/synchronized via a data-fetching layer with caching, background refresh, and offline persistence; **client/UI state** (form drafts, view toggles) is kept separate and local.
- **GraphQL** powers aggregation-heavy consumption screens (single round-trip, low bandwidth, `MASTER_ARCHITECTURE ADR-004`); **REST commands** for writes.
- **Optimistic UI** for light interactions where safe, reconciled against server truth; **never** optimistic for scheduling correctness (a pinned room must be server-confirmed).
- **Idempotency keys** on all mutations for safe retry over flaky links (`MASTER_BACKEND §5.3`).

### ADR-FE-005 — Never render browser-storage as source of truth for scheduling data
**Rationale.** The server is the single scheduling truth (`MASTER_ARCHITECTURE §6`). Local storage is a **cache and an outbox**, never authority. Prevents offline drift from corrupting timetables.

---

## 10. Real-Time UX

- **Push (WebSocket/SSE)** delivers: live solve progress, "timetable changed," substitution assignments, workflow decisions.
- Degrades to polling on constrained clients.
- The UI **reconciles pushed changes** into the local replica and highlights what changed (no silent mutation under the user's eyes).

---

## 11. Design System & Consistency

- A **shared design system** (tokens, components, patterns) ensures every surface feels like one product while allowing **tenant branding** (logo, colors within accessible bounds — govt/school identity) as *configuration*.
- Components are **label- and locale-aware by default** (a `<GroupLabel/>` renders the tenant's word in the user's language automatically).
- The **frontend-design** skill governs concrete visual/token decisions at build time to avoid templated, generic aesthetics.

---

## 12. Performance Budgets (frontend)

| Metric | Target | Why |
|---|---|---|
| Consumption app first meaningful view | fast on low-end phones & poor networks | core segment reality |
| Offline "today" view | instant (local replica) | rural teachers |
| Manual-edit validation feedback | <100ms (in-memory) | fluid authoring |
| Timetable screen data | single aggregated read (GraphQL) | low bandwidth |
| Bundle size (consumption) | tightly budgeted, code-split | low-end devices |

---

## 13. Frontend Invariants (non-negotiable)

1. **The UI never displays abstract primitives** — always tenant vocabulary, then localized.
2. **Screens are generated from effective config + capabilities**, never hard-coded per segment.
3. **Consumption is local-first; authoring is online-only; the UI always states its mode.**
4. **Browser storage is cache/outbox, never source of truth** for scheduling data.
5. **Every effective setting exposes its provenance** ("why this value?").
6. **Every failed solve renders a fixable explanation**, never a dead end.
7. **Localization, RTL, and pluggable calendars are structural**, applied everywhere.
8. **Accessibility and low-end performance are requirements**, not enhancements.

---

**END OF MASTER_FRONTEND.md**
