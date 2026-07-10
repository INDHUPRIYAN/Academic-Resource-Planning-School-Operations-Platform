# MASTER_BACKEND.md
### EduFlow AI — Backend Architecture
**Document Type:** Backend Architecture — Single Source of Truth
**Inherits from:** MASTER_PRODUCT, MASTER_ARCHITECTURE, MASTER_DATABASE, MASTER_SCHEDULER
**Version:** 1.0

---

## 0. Purpose

This document specifies **how the backend is built**: the internal module structure of the modular monolith, the Configuration Resolution Engine (the crown jewel at runtime), the Workflow Engine, the API design, the event/outbox machinery, and the offline sync backend. It defines *contracts and structure*, not line-level code.

---

## 1. Backend Technology Selection

Per `MASTER_ARCHITECTURE §9`, we record criteria then choose. **Concrete choice for the core:** a **strongly-typed, high-concurrency, IO-optimized runtime with a mature web/ORM ecosystem and a large hiring pool.** In practice this points to a modern typed backend (e.g., TypeScript/Node with a typed ORM, or Java/Kotlin, or Go, or Python-with-types — the *criteria* bind, and the team's depth is the tie-breaker). The **Scheduler Service** may use a different runtime optimized for constraint solving (`MASTER_ARCHITECTURE ADR-008`).

### ADR-BE-001 — One language for the core, polyglot only across service boundaries
**Rationale.** Team velocity and maintainability demand a single core language; the solver's specialized needs justify a boundary exception. No language sprawl inside the monolith (`ADR-008`).

Whatever is chosen must provide: first-class async IO, strong typing, a mature migration tool, row-level-security-capable DB driver, and solid observability libraries.

---

## 2. Internal Module Structure (the modular monolith)

Realizes `MASTER_ARCHITECTURE §2.1`. Each module is a **bounded context** with:
- A **public interface** (the only way other modules call it).
- **Private internals** (its own repositories/services — no other module touches its tables, Invariant #2).
- **Emitted events** (its contribution to the event spine).

```
core/
  platform/        (tenancy, provisioning, feature flags, packs)
  identity/        (actors, roles, permissions, sessions, authz)
  config/          (setting definitions, config values, RESOLUTION ENGINE)
  academic/        (org units, subjects, curriculum, learner-groups, resources)
  scheduling/      (assignment store, schedule lifecycle, solve orchestration)
  workflow/        (state-machine engine, instances)
  customfields/    (definitions + typed values)
  reporting/       (report definitions; heavy generation is an extracted svc)
  comms/           (notification rules/templates; fan-out is an extracted svc)
  audit/           (event spine projections, audit queries)
  shared/          (tenant context, i18n, errors, outbox, cache, search client)
```

### ADR-BE-002 — Enforce module boundaries with architectural fitness tests
**Decision.** Cross-module DB access and illegal imports are **failed by CI** (dependency/fitness tests), not just code review. **Rationale.** A modular monolith rots into a big ball of mud without automated enforcement (`MASTER_ARCHITECTURE` risk table). Boundaries drawn today enable future service extraction; they must be *mechanically* protected.

### 2.1 Layering within a module
Each module follows a clean layering: **API/handler → application service (use-cases) → domain → persistence.** The domain layer holds business rules and is framework-agnostic and unit-testable in isolation. This is a hard guideline in `MASTER_CODING_GUIDELINES`.

---

## 3. The Configuration Resolution Engine (runtime crown jewel)

Storage is in `MASTER_DATABASE §3`; here is the **runtime behavior**. Every module reads behavior *through* this engine (`MASTER_ARCHITECTURE §2.2`) — this is how "difference is data, not code" executes.

### 3.1 The resolution function
```
resolve(setting_key, entity_context, config_version) -> { value, provenance }
```
- Walks the entity's layer chain (group → program → campus → tenant → pack → platform).
- Applies **locks** (a locked higher layer short-circuits lower overrides).
- Returns the value **and** the provenance chain (which layer/entity/version decided it) → powers the "why this value?" UI (`MASTER_FRONTEND`) and Principle #7.

### 3.2 It is a pure, cached, deterministic function
- **Pure:** same inputs (including `config_version`) → same output. No hidden state.
- **Cached:** keyed `(tenant, config_version, entity, setting_key)`. Config is the most-read data in the system; the cache is **mandatory** (`MASTER_DATABASE §8`).
- **Invalidated on publish:** publishing a new `config_version` invalidates that tenant's cache namespace.

### ADR-BE-003 — Config resolution is a pure function of an immutable config-version
**Rationale.** Purity + immutability make it cacheable, testable, reproducible, and explainable. Because a published `schedule` pins a `config_version`, we can replay *exactly* how the system behaved historically (Principle #6). ❌ *Mutable "current settings" reads* rejected — non-reproducible, cache-hostile, and unexplainable historically.

### 3.3 Effective-config API
The backend exposes an **effective configuration** read for any entity context (used pervasively by other modules and the frontend), always accompanied by provenance. Bulk resolution (resolve many keys for a screen) is batched to avoid chattiness (helps low-bandwidth clients).

---

## 4. The Workflow Engine

Realizes `MASTER_PRODUCT §4.2` and `MASTER_DATABASE §2.7`. Approval chains, leave, substitution, config publish — all are **configurable state machines**, not hard-coded flows.

- **`workflow_definition`** = states + transitions + **guards** (who may transition, expressed via roles/permissions) + **actions** (emit event, notify, mutate entity).
- The engine advances **`workflow_instance`**s, enforcing guards through the identity module and recording every transition as a domain event.

### ADR-BE-004 — Workflows are data-driven state machines
**Rationale.** Every segment approves things differently (a government school's timetable sign-off vs. a coaching centre's none). Hard-coding flows would fork per segment (violates Principle #1). A generic state-machine engine + configured definitions serves all. ❌ *Hard-coded approval logic* rejected. ❌ *Full BPMN engine* considered but rejected for v1 as over-heavy; our constrained state-machine model covers the needed cases with far less complexity (revisit in roadmap if needed).

---

## 5. API Design

### 5.1 Style (per MASTER_ARCHITECTURE ADR-004)
- **REST for commands/writes** — explicit, versioned (`/v1/…`), centrally validated and audited.
- **GraphQL read-layer for aggregation-heavy consumption** (timetable/dashboard screens) — single round-trip, low-bandwidth-friendly.

### 5.2 Command model & validation
- Writes are **commands** with a single responsibility (`PublishSchedule`, `AssignSubstitution`, `CreateConstraint`).
- Every command: authorized (identity module) → validated (domain rules + config) → executed in a transaction that writes business rows **and** the outbox event atomically.
- Validation errors are **structured and explainable** (field-level, human-readable, localized) — never a bare 400.

### 5.3 Idempotency & concurrency
- Mutating endpoints accept an **idempotency key** (safe retries over flaky networks — critical for the rural segment and offline replay).
- Optimistic concurrency via `row_version` (`MASTER_DATABASE §6.2`); conflicts return a structured "someone else changed this" with the current state.

### 5.4 Versioning & compatibility
- Explicit `/v1`; **additive evolution**; deprecations measured in quarters (Principle #10). Contract tests guard against accidental breaks (`MASTER_TESTING`).

### 5.5 Pagination, filtering, rate limits
- Cursor-based pagination (stable under writes); tenant-tier-aware rate limits (noisy-neighbor control, `MASTER_ARCHITECTURE §3.2`).

---

## 6. Event & Outbox Machinery

Realizes `MASTER_ARCHITECTURE ADR-005` and `MASTER_DATABASE §7`.

- **Transactional outbox:** business write + event row committed atomically; a **dispatcher** publishes to the event spine after commit → **no lost/duplicate events**.
- **Consumers** (audit projection, search indexer, webhook dispatcher, real-time push, warehouse feed) are **idempotent** and **tolerant readers** (handle new event fields gracefully).
- **Events are versioned**; schema evolution never breaks existing consumers (tolerant reader pattern).
- **Webhooks** let tenant integrations subscribe (`MASTER_PRODUCT §6.8`) with signed payloads, retries, and dead-lettering.

### ADR-BE-005 — Outbox pattern over dual-writes
**Rationale.** Dual-writing to DB + message bus loses events on partial failure. Outbox guarantees the event iff the transaction committed — essential because events are our audit and reproducibility substrate. ❌ *Direct publish inside handler* rejected (unreliable).

---

## 7. Offline Sync Backend

Realizes `MASTER_ARCHITECTURE ADR-006` (local-first consumption, intent-based writes).

- **Delta sync endpoint:** client sends a **sync token**; server returns changes since that token for the client's **scoped dataset** (my timetable, my groups, today's changes). Efficient over poor links.
- **Scoped subscriptions:** a teacher syncs only their data (privacy + bandwidth).
- **Intent endpoints** (distinct from raw writes): the client submits *intent* ("accept this swap"); the server **validates against current authoritative state** and may accept or reject-with-reason. The server remains the single source of scheduling truth — offline can never violate constraints (`MASTER_ARCHITECTURE §6`).
- **Conflict handling:** consumption data is server-authoritative; intent writes reconcile explicitly. Idempotency keys make replay safe.

---

## 8. Job Orchestration

Heavy/async work (solve, bulk import, report, notification fan-out) runs as **durable jobs**:
- Dispatched to a queue; processed by the relevant **extracted service** (`MASTER_ARCHITECTURE §2`).
- **Per-tenant fair queuing + concurrency caps** (noisy-neighbor, `§3.2`).
- Jobs report **progress + result via events** (live UI).
- Jobs are **retryable and idempotent**; solver jobs are self-contained snapshots (`MASTER_SCHEDULER §4.1`) so they can run on preemptible compute.

---

## 9. Identity & Authorization (backend view)

- **AuthN:** central identity; supports SSO/OAuth/OIDC and, for low-tech tenants, simpler credential flows; MFA where configured. (Detail in `MASTER_SECURITY`.)
- **AuthZ:** every command/query passes a **central authorization check** that consults the identity module: *does this actor, in this org-scope, hold a role granting this capability?* Because roles/permissions are **data** (`MASTER_DATABASE §2.2`), authorization itself is configuration-driven. Scope (org_unit) narrows access (HOD sees only their department).

### ADR-BE-006 — Centralized, data-driven authorization checked on every operation
**Rationale.** Scattered ad-hoc permission checks are how leaks happen. One choke-point, fed by configured roles, enforced uniformly, audited on every decision. ❌ *Per-endpoint bespoke checks* rejected (inconsistent, unauditable).

---

## 10. Caching Strategy

| What | Cache | Invalidation |
|---|---|---|
| Resolved config values | keyed by config-version | on publish (version bump) |
| Authorization decisions | short-TTL per actor+scope | on role/assignment change |
| Timetable read projections | denormalized store | on schedule publish/change event |
| Reference/catalog data (packs, templates) | long-TTL | on platform release |
| Search results | index-backed | event-driven reindex |

Immutability-by-version (config, schedules) makes caching safe and simple — a recurring architectural payoff.

---

## 11. Error Handling, Validation & Localization

- **Errors are structured, typed, and localized** — every user-facing error carries a stable code + a translatable, human-readable message (`MASTER_PRODUCT` Principle #9). No raw stack traces to clients.
- **Validation is layered:** transport (shape) → command (business) → domain invariants → DB constraints (last line). Each layer returns actionable messages.
- **Explainability extends to errors:** a rejected substitution says *why* ("would exceed Ms. Rao's max consecutive load").

---

## 12. Observability (backend)

- **Structured logs** with `{tenant, actor, trace_id, config_version}` on every line.
- **Distributed tracing** core → solver → back (a solve is one traceable story).
- **Metrics:** config-cache hit rate, solve queue depth/time, API latency per tier, sync lag, workflow throughput, event-dispatch lag.
- **Health/readiness** endpoints per service; SLO dashboards mapped to `MASTER_PRODUCT §8`.

---

## 13. Backend Invariants (non-negotiable)

1. **No module touches another module's tables** (CI-enforced).
2. **Every read of behavior goes through the Config Resolution Engine** — no segment logic in code.
3. **Every write is authorized, validated, and emits an atomic outbox event.**
4. **Config resolution is pure and version-pinned** (reproducible, cacheable).
5. **The interactive path never runs a solve** — always async job + events.
6. **Offline intent writes are validated server-side; the server is the single scheduling truth.**
7. **APIs are versioned; no silent breaking changes; contract-tested.**
8. **Authorization is centralized and data-driven; every decision is audited.**

---

**END OF MASTER_BACKEND.md**
