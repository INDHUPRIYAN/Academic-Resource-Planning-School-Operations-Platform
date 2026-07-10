# MASTER_ARCHITECTURE.md
### EduFlow AI — System & Technical Architecture
**Document Type:** Technical Architecture — Single Source of Truth
**Inherits from:** MASTER_PRODUCT.md
**Version:** 1.0

---

## 0. Purpose & Reading Order

This document translates the product constitution into a technical shape. It defines the **macro-architecture** (how the system is decomposed), the **multi-tenancy model**, the **configuration engine placement**, the **scheduler-as-workload isolation**, and the **cross-cutting technical decisions** (transport, events, offline, observability).

It does **not** define schemas (see `MASTER_DATABASE.md`), the solver internals (see `MASTER_SCHEDULER.md`), or per-service code structure (see `MASTER_BACKEND.md`). It sets the boundaries those documents fill in.

Every architectural decision is recorded as an **ADR-style block**: Decision → Context → Alternatives → Rationale → Consequences.

---

## 1. Architectural Drivers (what forces the shape)

These are the product requirements from `MASTER_PRODUCT.md` that have the highest architectural leverage. The architecture exists to serve *these*, in priority order:

1. **Configuration-as-data** (Principle #1) → we need a **configuration resolution engine** as a first-class, central, cached service that everything reads through.
2. **Multi-tenancy at 100k+ tenants** (§8) → tenant isolation, noisy-neighbor control, and per-tenant scaling are foundational, not retrofitted.
3. **Scheduler is a pluggable workload** (Principle #4) → the solver must be a **separately scalable, isolatable compute service**, not embedded in the request path.
4. **Offline-first consumption** (Principle #5) → API and sync design must assume intermittent connectivity for a core segment.
5. **Explainability & auditability** (Principles #6, #7) → an **event-sourced audit spine** and provenance are architectural, not feature-level.
6. **Backward compatibility for 10 years** (Principle #10) → versioned APIs, versioned config, expand-migrate-contract schema discipline.
7. **Optional hard isolation for government tenants** (§8) → the deployment topology must support both shared and dedicated tenant hosting from the same codebase.

⚠️ **CHALLENGE: Do these drivers demand microservices, or is that cargo-culting?**
They do **not** demand fine-grained microservices. They demand a small number of **independently scalable boundaries** where the scaling profiles genuinely differ (interactive API vs. heavy solver vs. async reporting). We adopt a **modular monolith + a few extracted heavy-compute services**, not a swarm of nano-services. Rationale below (ADR-001). Premature microservice decomposition is how a 5-person team drowns in distributed-systems tax before finding product-market fit.

---

## 2. Macro-Architecture: The "Modular Monolith + Extracted Workloads" Pattern

### ADR-001 — Modular Monolith Core with Extracted Compute Workloads

**Decision.** The system is a **modular monolith** for the transactional/interactive core (config, identity, academic data, workflows, consumption APIs), plus a small set of **independently deployed workload services** for compute profiles that differ radically from interactive traffic:

- **Scheduler Service** (CPU-heavy, long-running, burst-scaled, isolatable).
- **Reporting / Export Service** (memory & IO-heavy, batchy).
- **Notification/Comms Service** (IO-bound fan-out, third-party rate limits).
- **Sync/Offline Gateway** (stateful-ish, conflict resolution).
- **AI Service** (GPU/inference or external-LLM-bound, rate-limited, cost-sensitive).

**Context.** 100k tenants, tiny-team-at-start reality, wildly different scaling needs per workload, and a 10-year horizon.

**Alternatives considered.**
- ❌ *Full microservices from day one.* Rejected: distributed transactions, network failure modes, and operational overhead with no PMF justification. Violates the "start lean" reality and endangers the timeline.
- ❌ *Pure monolith (solver inline).* Rejected: a 3-minute college solve would block web workers, and one heavy tenant would degrade all. The scheduler *must* be extractable.
- ✅ *Modular monolith + extracted heavy workloads.* Chosen.

**Rationale.** The modular monolith keeps the transactional core (which shares a database and needs strong consistency) simple and fast to build, while the *genuinely different* compute profiles are isolated. Module boundaries inside the monolith are enforced by clear internal contracts, so any module can be extracted later **if and only if** load justifies it — the boundaries are drawn now, the network hops are deferred.

**Consequences.**
- Internal modules communicate via **well-defined interfaces**, never by reaching into each other's tables. This discipline is enforced in `MASTER_CODING_GUIDELINES.md`.
- The extracted services communicate with the core via **async messaging** (jobs/events) and **versioned internal APIs**.
- We pay a *design* cost now (clean boundaries) to avoid a *rewrite* cost later.

### 2.1 The module map (inside the core monolith)

```
┌──────────────────────────────────────────────────────────────┐
│                      EDUFLOW CORE (monolith)                    │
│                                                                │
│  ┌────────────────┐  ┌────────────────┐  ┌─────────────────┐  │
│  │  Identity &    │  │  Configuration  │  │   Tenancy &     │  │
│  │  Access (RBAC/ │  │  Engine (7-layer│  │   Provisioning  │  │
│  │  ABAC)         │  │  resolution)    │  │                 │  │
│  └────────────────┘  └────────────────┘  └─────────────────┘  │
│  ┌────────────────┐  ┌────────────────┐  ┌─────────────────┐  │
│  │ Academic Data  │  │  Workflow Engine│  │  Timetable /    │  │
│  │ (groups, subj, │  │  (state machines│  │  Assignment     │  │
│  │  resources)    │  │  approvals)     │  │  Store          │  │
│  └────────────────┘  └────────────────┘  └─────────────────┘  │
│  ┌────────────────┐  ┌────────────────┐  ┌─────────────────┐  │
│  │  Audit / Event │  │  Custom Fields  │  │  Reporting      │  │
│  │  Spine         │  │  & Forms        │  │  (definitions)  │  │
│  └────────────────┘  └────────────────┘  └─────────────────┘  │
│                                                                │
│  Cross-cutting: config-read cache, tenant context, i18n,      │
│  search index, file/document refs, feature flags              │
└──────────────────────────────────────────────────────────────┘
        │ async jobs / events            │ versioned internal API
        ▼                                ▼
┌───────────────┐ ┌──────────────┐ ┌──────────────┐ ┌──────────────┐
│  Scheduler    │ │  Reporting/  │ │  Notification│ │  AI Service  │
│  Service      │ │  Export Svc  │ │  /Comms Svc  │ │  (NL→rules,  │
│  (solver)     │ │              │ │              │ │  explain)    │
└───────────────┘ └──────────────┘ └──────────────┘ └──────────────┘
        ▲
┌───────────────┐
│  Sync/Offline │  ← serves local-first clients, reconciles
│  Gateway      │
└───────────────┘
```

### 2.2 Why the Configuration Engine is central

The Configuration Engine is the **beating heart**. Every other module resolves behavior through it. It is not a settings CRUD; it is a **resolution service** that, given `(setting_key, entity_context)`, walks the 7-layer stack (`MASTER_PRODUCT §4.1`), applies locks, and returns `(value, provenance)`.

- It is **read-dominant and cacheable** — resolution results are cached per `(tenant, config-version, entity, key)` and invalidated on config publish.
- It exposes **provenance** so any consumer (and the UI) can answer "why this value?".
- No module hard-codes segment behavior; they *ask* the engine.

This is the mechanism by which "the difference is data, not code" becomes literally true in the architecture.

---

## 3. Multi-Tenancy Architecture

### ADR-002 — Hybrid Tenancy: Shared-Schema Pooled by default, Dedicated on demand

**Decision.** Three tenancy tiers on **one codebase**:

| Tier | Data model | Who gets it | Isolation |
|---|---|---|---|
| **Pooled** (default) | Shared DB, shared schema, mandatory `tenant_id` on every row + row-level security | Vast majority (K-12, coaching) | Logical, enforced at DB + app |
| **Bridge** | Shared cluster, **schema-per-tenant** or dedicated database | Large chains, mid regulated | Stronger logical |
| **Silo** | Dedicated database / dedicated deployment | Government, large universities, data-residency mandates | Physical/near-physical |

**Context.** 100k tenants demand pooling for margin; government/regulated tenants demand isolation for trust and law (`MASTER_PRODUCT §8`).

**Alternatives.**
- ❌ *Pooled-only.* Cannot satisfy data-residency/government isolation requirements.
- ❌ *Silo-only (DB per tenant).* Cannot economically reach 100k tenants (connection, migration, and ops explosion).
- ✅ *Hybrid with a tenancy abstraction.* Chosen.

**Rationale.** A **tenant-routing layer** resolves, per request, *where* a tenant's data lives and injects the tenant context; the rest of the code is tenancy-agnostic. Moving a tenant Pooled→Silo is an **operational migration, not a code change**.

**Consequences.**
- **Every** data-access path passes through tenant context; there is no query without a tenant scope (enforced, not conventional — see `MASTER_SECURITY.md` & `MASTER_DATABASE.md`).
- Cross-tenant queries are impossible by construction except for explicitly-privileged platform operations, which are separately audited.
- Migrations must run across pooled + N dedicated stores; the deployment pipeline (`MASTER_DEPLOYMENT.md`) treats this as first-class.

### 3.1 Tenant context propagation

Every inbound request establishes an immutable **Tenant Context** `{tenant_id, org_scope, actor, roles, locale, config_version}` at the edge. This context:
- Is attached to every DB query (scoping), every log line, every event, every cache key.
- Is the primary key of nearly everything: **there is no global data except the platform catalog and Configuration Packs.**

### 3.2 Noisy-neighbor & fairness

- Heavy operations (solve, bulk report) are **queued per tenant** with fair scheduling and per-tenant concurrency caps, so one university's giant solve can't starve 500 coaching centres.
- Rate limits and quotas are **tenant-tier-aware** (config, of course).

---

## 4. The Scheduler as an Isolated Workload

### ADR-003 — Scheduler is a stateless, horizontally-scalable, async compute service

**Decision.** The Scheduler Service:
- Receives a **self-contained solve job** (the problem is fully materialized: groups, resources, slots, compiled constraints, config-version snapshot) — it does **not** reach back into the core DB mid-solve.
- Runs **stateless**; any worker can pick up any job; scales horizontally on queue depth.
- Streams **progress + partial solutions + explanations** back via events.
- Is **isolatable** so a runaway solve is contained (CPU/time budgets, cancellation).

**Rationale.**
- Solves are bursty and heavy; decoupling protects interactive latency.
- A materialized problem snapshot makes solves **reproducible** (tie to config-version → Principle #6) and **cacheable**.
- Statelessness makes scaling and failure-recovery trivial (retry the job).

**Consequences.**
- There is a **problem-compilation step** in the core that snapshots everything the solver needs (this is also where the constraint linter runs — `MASTER_SCHEDULER.md`).
- Solver worker fleets can be scaled/priced independently, and even run on spot/preemptible compute since jobs are retryable.

⚠️ **CHALLENGE: Materializing the whole problem is expensive for a 500-group university.** True; large problems get **incremental/partitioned solves** (e.g., by independent sub-graphs — a department with no shared resources solves independently). Partitioning strategy is a scheduler concern; the *architecture* only mandates that the job be self-contained and cancellable.

---

## 5. Communication Patterns

### 5.1 Synchronous (request/response)
- Client ↔ Core for interactive reads/writes (config, academic data, consumption).
- Core ↔ extracted services only where a *fast* answer is needed (rare); default is async.
- **API style:** primarily **REST with a resource model**, versioned (`/v1/…`). A **GraphQL read-layer** is offered for the frontend's aggregation-heavy consumption screens (a class timetable pulls from many entities) to avoid over-fetching and N+1 round-trips over poor connections.

### ADR-004 — REST for writes/commands, GraphQL for complex reads
**Rationale.** Writes benefit from REST's explicitness, cacheability, and simple versioning; the frontend's dashboard/timetable reads benefit from GraphQL's single-round-trip aggregation (critical on low-bandwidth). We deliberately avoid GraphQL for mutations to keep write-side auditing and validation centralized and simple. ❌ *GraphQL-everything* rejected (write complexity, caching, and rate-limiting harder). ❌ *REST-only* rejected (chatty consumption screens hurt offline/rural).

### 5.2 Asynchronous (events & jobs)
- **Jobs:** solve, bulk import, report generation, notification fan-out — dispatched to a durable queue, processed by the relevant workload service.
- **Events:** an **event spine** (append-only) is the backbone of audit, provenance, integrations (webhooks), and real-time UI updates. Key domain events: `ConfigPublished`, `TimetableGenerated`, `TimetablePublished`, `SubstitutionAssigned`, `LeaveDecided`, `ConstraintViolated`.

### ADR-005 — Event spine for audit, integration, and real-time
**Decision.** All state-changing operations emit domain events to an append-only log; consumers include the audit store, the search indexer, webhook dispatcher, and the real-time push gateway.
**Rationale.** One mechanism serves auditability (Principle #6), integrations (§MASTER_PRODUCT 6.8), and live UI — instead of three bespoke systems. Events are the reproducibility substrate.
**Consequences.** Events are **versioned and immutable**; consumers are idempotent; we adopt outbox-style reliability so a DB commit and its event are atomic.

### 5.3 Real-time to clients
- **Push over WebSocket/SSE** for "your timetable changed" and live solve progress.
- Gracefully degrades to polling for constrained clients.

---

## 6. Offline-First & Sync Architecture

### ADR-006 — Local-first consumption with a Sync Gateway and explicit conflict policy

**Decision.** Consumption clients (teacher/student/parent apps, and admin on poor connections) are **local-first**: they hold a local replica of the data they consume, work offline, and reconcile via the **Sync Gateway**.

**Context.** Government/rural is a core segment (`MASTER_PRODUCT` Principle #5). Teachers checking today's schedule in a low-signal school cannot depend on a live call.

**Design.**
- **Read replicas sync down:** a client subscribes to a scoped dataset (my timetable, my groups, today's substitutions) and keeps it locally.
- **Writes are queued locally** and replayed on reconnect (e.g., a teacher marking a substitution accepted).
- **Conflict policy is explicit and domain-aware:** consumption data is server-authoritative (last-writer is the server); the rare offline *write* (accept swap, request leave) uses **command intent** semantics — the client sends *intent*, the server validates against current authoritative state and may reject with a reason, rather than blindly overwriting.

**Alternatives.**
- ❌ *CRDT-everything.* Overkill and dangerous for a scheduling domain where the server must enforce constraints; two teachers can't both "win" a room. Rejected.
- ❌ *Online-only with a cache.* Fails the core segment. Rejected.
- ✅ *Local-first reads + intent-based writes validated server-side.* Chosen — the server remains the single source of scheduling truth (constraints can't be violated offline), while consumption stays usable.

**Consequences.** The API must expose **scoped, incremental sync** (delta since last sync token) and **intent endpoints** distinct from raw writes. This shapes `MASTER_BACKEND.md` and `MASTER_FRONTEND.md`.

⚠️ **CHALLENGE: Does offline-first apply to the admin/scheduler too?** No. **Generation, configuration, and publishing are online operations** (they require the authoritative constraint engine). Offline-first is a *consumption* and *light-interaction* guarantee, not an authoring one. This scoping keeps the hard problem (offline constraint-solving) off the table.

---

## 7. Data Architecture (topology only; schema in MASTER_DATABASE)

### 7.1 Polyglot persistence, chosen per job

| Store | Purpose | Why |
|---|---|---|
| **Primary relational DB** (per tenancy tier) | Transactional core: config, academic data, assignments, workflows | Strong consistency, relational integrity for scheduling correctness |
| **Event/audit store** (append-only) | Domain events, audit spine | Immutable, replayable, integration source |
| **Search index** | Full-text & faceted search across entities | Fast lookups the RDBMS shouldn't serve |
| **Cache** | Config resolution results, session, hot reads | Config engine is read-heavy; caching is essential to scale |
| **Object storage** | Generated PDFs, exports, documents, uploads | Cheap, durable blob storage |
| **Analytics/warehouse** (async) | Reporting at scale, cross-tenant platform analytics (privacy-scoped) | Separate OLAP from OLTP so reports don't hurt live traffic |

### ADR-007 — Relational core is the source of truth; others are derived/specialized
**Rationale.** Scheduling correctness is fundamentally relational and constraint-laden; consistency is non-negotiable (you cannot double-book a room). The RDBMS is authoritative. Search, cache, warehouse, and analytics are **derived** and rebuildable from the relational core + event log. This prevents the classic "which store is right?" corruption. ❌ *NoSQL-first core* rejected — scheduling integrity needs transactions and constraints.

### 7.2 Configuration storage note
Config lives in the relational core but is modeled as **versioned, layered records** (see `MASTER_DATABASE.md`). The resolution engine reads it heavily; hence the dedicated cache.

---

## 8. Cross-Cutting Concerns (architectural)

### 8.1 Identity & Access
- Central identity; **tenant-defined RBAC + ABAC** (roles and permissions are data — `MASTER_PRODUCT §4.2`).
- Access checks are centralized in an authorization service that the config engine feeds (a role's permissions are... configuration). Detailed in `MASTER_SECURITY.md`.

### 8.2 Internationalization (structural)
- Locale is part of Tenant Context; strings, calendars, scripts, number/date formats resolve per locale.
- **Calendars are pluggable** (Gregorian + regional/academic calendars) because term/holiday logic depends on them — this is domain, not translation.

### 8.3 Observability
- **Structured logging** with tenant/actor/trace context on every line.
- **Distributed tracing** across core → workload services (a solve is traceable end-to-end).
- **Metrics** per tenant tier and per workload (solve time, queue depth, config-cache hit rate, sync lag).
- **SLOs** map to the NFR table in `MASTER_PRODUCT §8`.

### 8.4 Feature flags & progressive rollout
- Flags are tenant/tier-scoped; new capabilities (and new Configuration Pack versions) roll out gradually and are reversible.

### 8.5 API versioning & backward compatibility
- **Explicit major versions** (`/v1`), additive-by-default evolution, deprecation windows measured in quarters (10-year horizon → Principle #10). No breaking change without a version and a migration path.

---

## 9. Technology Selection Philosophy (not a lock-in list)

We record **selection criteria** rather than dogmatic brand names, because a 10-year document must survive tooling churn. Concrete choices live in `MASTER_BACKEND.md`, `MASTER_FRONTEND.md`, and `MASTER_DEPLOYMENT.md`, but must satisfy:

- **Core language/runtime:** strong typing, mature ecosystem, good concurrency for IO-bound APIs, large hiring pool. *(Backend doc selects specifics.)*
- **Scheduler runtime:** access to mature **constraint-programming / optimization** libraries and CPU efficiency. May differ from the core language — the extracted-service boundary *permits* this. *(Scheduler doc selects.)*
- **Datastore:** a battle-tested relational engine with row-level security, strong transactional guarantees, and mature replication/partitioning.
- **Frontend:** component-driven, strong i18n & offline (service-worker/local-store) support, accessible.
- **Infra:** containerized, orchestrated, supporting both pooled and dedicated deployment topologies.

### ADR-008 — Polyglot allowed *only* across service boundaries, never within a module
**Rationale.** The scheduler may use a different language optimized for solving; the core stays single-language for team velocity and maintainability. We do **not** allow language sprawl inside the monolith. This bounds the DX cost of polyglot while capturing its benefit where it matters (the solver).

---

## 10. Environments & Topology (summary; detail in MASTER_DEPLOYMENT)

- **Environments:** dev → staging → production, plus **tenant-isolated production stacks** for Silo-tier customers.
- **Topology per tier:** Pooled tenants share the standard stack; Silo tenants get a templated, independently-deployed stack from the *same* artifacts (config differs, code does not).
- **Blue/green + expand-migrate-contract** for zero-downtime schema evolution across all stores.

---

## 11. Architectural Risks & Mitigations

| Risk | Mitigation | Owner doc |
|---|---|---|
| Modular monolith degrades into a big ball of mud | Enforced module boundaries + interface contracts + fitness tests | MASTER_CODING_GUIDELINES |
| Config engine becomes a performance bottleneck (every read hits it) | Aggressive per-version caching + provenance memoization | MASTER_BACKEND |
| Solver snapshot cost for huge tenants | Problem partitioning + incremental solves | MASTER_SCHEDULER |
| Offline write conflicts violate constraints | Intent-based writes, server-authoritative validation | MASTER_BACKEND/FRONTEND |
| Multi-store consistency drift (search/cache stale) | Rebuildable-from-source + event-driven reindex + idempotent consumers | MASTER_DATABASE |
| Silo tenants multiply ops burden | Same-artifact templated deploys, automated fleet migrations | MASTER_DEPLOYMENT |
| Event spine schema evolution breaks consumers | Versioned events, tolerant readers | MASTER_BACKEND |

---

## 12. Non-Negotiable Architectural Invariants

1. **No query without a tenant scope.**
2. **No module reads another module's tables directly.**
3. **The scheduler never blocks the interactive request path.**
4. **Every state change emits an immutable, versioned event.**
5. **Config is resolved through the engine, never hard-coded per segment.**
6. **The relational core is the single source of scheduling truth; offline never overrides constraints.**
7. **Every artifact deploys identically to pooled and silo topologies — config differs, code does not.**
8. **Every public API is versioned; no silent breaking changes.**

---

**END OF MASTER_ARCHITECTURE.md**
