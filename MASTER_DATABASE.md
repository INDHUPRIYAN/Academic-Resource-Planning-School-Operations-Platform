# MASTER_DATABASE.md
### EduFlow AI — Data Model & Database Architecture
**Document Type:** Data Architecture — Single Source of Truth
**Inherits from:** MASTER_PRODUCT.md, MASTER_ARCHITECTURE.md
**Version:** 1.0

---

## 0. Purpose

This document defines **how data is modeled and stored** so that the product thesis — *the difference between segments is DATA, not CODE* — is literally realized in the schema. It specifies the domain entities, the layered-configuration storage, custom fields, versioning, tenant isolation at the data layer, and the integrity rules that keep scheduling correct.

It is **relational-first** (per `MASTER_ARCHITECTURE ADR-007`: the relational core is the single source of truth). It describes *logical* models and *physical* strategy, not vendor DDL. Concrete migrations follow `MASTER_CODING_GUIDELINES.md`.

---

## 1. Data Modeling Principles

1. **Every business row carries `tenant_id`.** No exceptions except the global platform catalog and Configuration Packs. Row-level security enforces it (Invariant #1 from architecture).
2. **Entities are stable; configuration is variable.** We model the five primitives generically (`MASTER_PRODUCT §5`) and push variability into configuration + custom fields, *not* into new tables per segment.
3. **Nothing is hard-deleted.** Soft-delete + audit for business entities; history is a feature (compliance, reproducibility).
4. **Time is explicit.** Academic data is bi-temporal where it matters: *valid time* (which academic year/term a fact applies to) and *system time* (when we recorded it).
5. **Configuration is versioned like code.** A published timetable pins the exact config version it used (`MASTER_PRODUCT §4.4`).
6. **Referential integrity is enforced in the DB, not just the app.** Scheduling correctness depends on it (you cannot reference a deleted room).
7. **Custom fields are first-class and typed**, never a JSON dumping ground with no validation.
8. **Read models may be denormalized; the write model stays normalized.** Denormalization is derived and rebuildable.

---

## 2. The Core Domain Schema (logical)

Below, entities are grouped by module. Relationships and the *why* matter more than column lists; representative attributes are shown. All tables implicitly include: `id`, `tenant_id`, `created_at`, `updated_at`, `created_by`, `updated_by`, `deleted_at` (soft delete), and `row_version` (optimistic concurrency).

### 2.1 Tenancy & Hierarchy

**`tenant`** — the institution/group.
- `name`, `tenancy_tier` (pooled|bridge|silo), `data_region`, `status`, `adopted_pack_id`, `adopted_pack_version`, `primary_locale`.

**`org_unit`** — a node in the *configurable* hierarchy (the depth/naming is data).
- `parent_org_unit_id` (self-ref → arbitrary-depth tree), `org_unit_type_id`, `name`, `code`, `sort_order`.
- **`org_unit_type`** — tenant-defined node types ("Campus", "Wing", "Department", "Branch"). *This is why a 2-level coaching chain and a 5-level school group share one schema.*

⚠️ **CHALLENGE: An adjacency-list tree is slow for "all descendants" queries.** Correct. We store the tree as adjacency-list (source of truth) **plus** a materialized closure/path (`org_unit_closure` or a `path` column) for fast subtree queries, rebuilt on hierarchy change. Read speed for scoping (very frequent) justifies the maintained redundancy.

### 2.2 Identity & Access

**`actor`** — a principal (human or system).
- `type` (user|integration|external_auditor), `auth_ref`, `status`, `default_locale`.

**`role`** — **tenant-defined** roles (not an enum). `name`, `description`, `is_system`.
**`permission`** — the platform's *capability catalog* (global): `capability_key` (e.g., `timetable.generate`, `config.publish`).
**`role_permission`** — which capabilities a role grants (data-driven RBAC).
**`actor_role_assignment`** — actor ↔ role, **scoped to an `org_unit`** (ABAC-ish): an HOD-Science role is granted *only within the Science department node*. This scoping is what makes "HODs see only their department" real. (Full model in `MASTER_SECURITY.md`.)

### 2.3 Academic Structure

**`academic_year`** — `name`, `starts_on`, `ends_on`, `status` (draft|active|archived).
**`term`** — semester/term/quarter within a year: `academic_year_id`, `name`, `sequence`, dates. (Colleges → semesters; K-12 → terms; coaching → rolling/none.)
**`day_type`** / **`day_cycle`** — supports odd/even days, rotating cycles, 6-day weeks. Configurable.

**`subject`** — a teachable subject/course. `name`, `code`, `subject_group_id` (streams), `credit_value` (nullable — colleges), `is_co_scholastic` (CBSE), `default_periods_per_week` (nullable).
**`subject_group` / `stream`** — Bio-Maths, Commerce, CS options pools, IB option blocks.
**`curriculum`** — binds subjects to a program/grade for a year (what Grade 10 studies this year), enabling year-over-year change without rewriting subjects.

### 2.4 The Five Primitives (the scheduling core)

**`learner_group`** — the cohort scheduled together (`MASTER_PRODUCT §5`). UI-labeled per tenant.
- `org_unit_id`, `name` (10-A / JEE-Morning / CS-301-Sec2), `learner_group_type_id`, `expected_size`, `curriculum_id`.
- **`learner_group_type`** — tenant vocabulary ("Section", "Batch", "Course-Section").

**`learner`** — individual student/enrollee (light in v1, deeper with SIS later).
- `learner_group_membership` — many-to-many with valid-time (a student changes sections mid-year; electives put a student in multiple groups).

**`resource`** — anything scarce a delivery consumes.
- `resource_type_id`, `name`, `capacity` (nullable — a room seats 40; a teacher "seats" 1), `home_org_unit_id`, `is_shareable_across_org_units` (coaching visiting faculty!).
- **`resource_type`** — tenant-defined ("Teacher", "Room", "Lab", "Projector", "Visiting-Faculty"). *This is how one schema models teachers and equipment and rooms uniformly.*
- **`resource_qualification`** — a teacher-resource can teach subjects X, Y (skills matrix); a lab-resource supports subjects P, Q.
- **`resource_availability`** — availability windows (a visiting faculty is only free Tue/Thu evenings; a lab is closed period 1). Bi-temporal.

**`deliverable_unit`** — a teachable, time-consuming unit that needs scheduling.
- `subject_id`, `learner_group_id`, `required_resource_spec` (needs a Chem-lab + a Chemistry-qualified teacher), `sessions_per_week` or `credit_hours`, `session_length`, `time_model_id`.
- This is the "demand" the scheduler must place.

**`time_model`** — the pluggable time strategy (`MASTER_ARCHITECTURE`, `MASTER_SCHEDULER`).
- `type` (period|block|credit|free), plus type-specific parameters.
**`time_slot`** — a concrete bookable interval generated from the time model + calendar.
- `day_type_id`, `sequence`/`start_time`/`end_time`, `slot_kind` (teaching|break|assembly).

**`assignment`** — the atom of a timetable: a validated binding.
- `deliverable_unit_id`, `time_slot_id`, `learner_group_id`, and via **`assignment_resource`** the one-or-more resources consumed (a lab session = teacher + lab room).
- `schedule_id` (which timetable version it belongs to), `status` (proposed|published|superseded), `locked` (manual pins).

### 2.5 Schedules & Timetables

**`schedule`** — a versioned set of assignments for a scope+period.
- `scope` (org_unit / program / whole-tenant), `academic_year_id`, `term_id`, `status` (draft|generated|published|archived), `config_version_id` (**pins the config used** → reproducibility), `generated_by_job_id`, `published_at`.
- Multiple candidate schedules can exist (compare solutions — `MASTER_SCHEDULER`); one is published.

**`schedule_change`** — daily-ops deltas over a published schedule (substitutions, room swaps) without regenerating: `original_assignment_id`, `new_resource_id`, `reason`, `effective_date`, `workflow_state`.

### 2.6 Constraints (stored as data)

**`constraint_definition`** — a tenant's composed rule (`MASTER_PRODUCT §4.3`).
- `constraint_template_id` (from the platform's constraint vocabulary), `hardness` (hard|soft|policy), `weight` (for soft), `scope` (which groups/resources it applies to), `parameters` (typed), `source` (manual|nl-assisted|pack), `natural_language_text` (what the user typed, for explainability).
- **`constraint_template`** — the platform-global vocabulary of primitives (single-occupancy, capacity, availability, max-consecutive, spread, preference…). Adding a new *kind* of rule = new template (rare, platform-level), not per-tenant code.

### 2.7 Workflows

**`workflow_definition`** — a configurable state machine (approval chains, leave, substitution). `entity_type`, `states`, `transitions`, `guards` (who can transition — ties to roles).
**`workflow_instance`** — a running instance on a specific entity, with `current_state`, `history`.

### 2.8 Assessment & Reporting (v1 scheduling-adjacent)

**`grading_scale`**, **`assessment_definition`**, **`exam`**, **`exam_schedule`** (exam timetabling reuses the scheduler), **`report_template`** (tenant-brandable, format-configurable → govt/board formats as data).

### 2.9 Communication

**`notification_template`**, **`notification_rule`** (event → channel(s) → audience), **`notification_log`**.

---

## 3. The Configuration Store (the crown jewel)

This is where `MASTER_PRODUCT §4` becomes physical. It must store a **7-layer, versioned, lockable, provenance-bearing** configuration.

### 3.1 Setting definitions vs. setting values

- **`setting_definition`** (global catalog): `setting_key`, `data_type`, `allowed_values`/schema, `default_value`, `is_lockable`, `category`, `applies_to_layer` (some settings only make sense at tenant level, some at group level). This is the *contract* of what's configurable.
- **`config_value`** (the actual overrides): `setting_key`, **`layer`** (platform|pack|tenant|campus|program|year|group), **`layer_entity_id`** (which campus, which group…), `value`, `is_locked`, `config_version_id`.

### 3.2 Versioning model

- **`config_version`** — an immutable snapshot label: `tenant_id`, `version_number`, `status` (draft|in_review|published), `published_at`, `published_by`, `parent_version_id`.
- Editing config creates a **draft version**; publishing freezes it. A `schedule` references a `config_version_id`, so we can always reconstruct "the rules on generation day."
- Config diffs between versions are computable (audit + pack-update merges).

### 3.3 Resolution (read path — implemented in backend, storage here)

The Configuration Engine (`MASTER_ARCHITECTURE §2.2`) resolves `(setting_key, entity_context, config_version)` by:
1. Determining the entity's layer chain (group → program → campus → tenant → pack → platform).
2. Selecting the nearest `config_value` in that chain (respecting `is_locked` from a *higher* layer, which short-circuits overrides).
3. Returning `(value, provenance=[layer, layer_entity_id, config_version])`.

Results are cached by `(tenant_id, config_version_id, entity_id, setting_key)` and invalidated on publish. **This is the most-read data in the system — caching is mandatory, not optional.**

### 3.4 Configuration Packs (global, versioned)

- **`config_pack`** (global): `name` (CBSE-K12…), `segment`, `version`, `status`.
- **`config_pack_content`**: the bundled defaults (hierarchy shape, roles, calendar, subjects, constraints, report templates, localization) — expressed in the same `config_value`/definition vocabulary so a pack is literally a pre-filled config layer.
- A tenant "adopts" a pack (records `adopted_pack_id/version`); pack values sit at the `pack` layer and are overridable by tenant layers. Pack updates are offered as non-destructive suggested merges.

---

## 4. Custom Fields & Forms (first-class extensibility)

Tenants add fields to core entities (UDISE code, batch fee-tier) without schema changes (`MASTER_PRODUCT §4.2`).

### ADR-DB-001 — Typed custom fields via a definition + typed-value model (not raw JSON blobs)

**Decision.** Custom fields use:
- **`custom_field_definition`**: `tenant_id`, `entity_type` (learner|learner_group|resource…), `field_key`, `data_type`, `validation_rules`, `is_required`, `is_reportable`, `is_searchable`.
- **`custom_field_value`**: `entity_type`, `entity_id`, `field_definition_id`, and typed value columns (or a validated typed JSON with a schema).

**Alternatives.**
- ❌ *Raw JSON column per entity.* Fast to build, but unvalidated, unindexable, unreportable, unsearchable → becomes a swamp. Rejected (violates Principle #7 of this doc).
- ❌ *Real columns per custom field (DDL at runtime).* Migrations per tenant, schema explosion at 100k tenants. Rejected.
- ✅ *Definition + typed-value (EAV-with-discipline), with validation, selective indexing for `is_searchable` fields, and materialized projections for hot reportable fields.* Chosen.

**Consequences.** We accept EAV's query cost, mitigated by: validation at write, indexing only flagged fields, and building **materialized read projections** for fields used heavily in reports. This is the pragmatic middle path between "JSON swamp" and "DDL explosion."

---

## 5. Multi-Tenancy at the Data Layer

Realizes `MASTER_ARCHITECTURE ADR-002` (Pooled/Bridge/Silo).

- **Pooled:** shared schema; **`tenant_id` on every row**; **database row-level security** so even a buggy query can't cross tenants; every index is `tenant_id`-leading.
- **Bridge:** schema-per-tenant or DB-per-tenant in a shared cluster; routing layer picks the schema/DB from Tenant Context.
- **Silo:** dedicated database/instance; same schema, deployed per tenant.

### ADR-DB-002 — Defense-in-depth tenant isolation
**Decision.** Isolation is enforced at **three** layers: (1) application always scopes by tenant context; (2) DB **row-level security** policies keyed on a session-set tenant variable; (3) leading `tenant_id` in every unique key/index so uniqueness is per-tenant (a "10-A" in tenant A never collides with tenant B).
**Rationale.** A single missed `WHERE tenant_id=` in app code must **still** be caught by RLS. Data leakage is a `MASTER_PRODUCT` *Critical* risk; one layer is insufficient.

---

## 6. Integrity, Concurrency & Temporal Rules

### 6.1 Scheduling integrity (the correctness backbone)
- **Uniqueness constraints prevent double-booking at the data layer**, not only in the solver: a partial unique index ensures a given `resource` cannot appear in two *published* assignments in the same `time_slot` on the same date. The solver produces valid schedules; the DB is the last line of defense against races and manual overrides.
- Capacity checks (group size ≤ room capacity) enforced as validated invariants on publish.

### 6.2 Concurrency
- **Optimistic concurrency** via `row_version` on interactive edits (two coordinators editing the same schedule → conflict surfaced, not lost).
- Publishing a schedule is a **transaction** that supersedes the prior published version atomically.

### 6.3 Temporal / bi-temporal
- Facts that change over an academic year (group membership, resource availability, curriculum) carry **valid-time ranges**; historical queries ("who was in 10-A in term 1?") remain answerable.
- System-time via audit/event spine (§7).

---

## 7. Audit, Events & History

Realizes `MASTER_ARCHITECTURE ADR-005` at the data layer.

- **`domain_event`** (append-only): `tenant_id`, `event_type`, `event_version`, `entity_ref`, `payload`, `actor`, `occurred_at`, `causation_id`, `correlation_id`. Immutable.
- **Outbox pattern:** state-change transactions write the business row **and** an outbox event atomically; a dispatcher publishes to the event spine → guarantees no lost/duplicated events.
- **`audit_log`** is a projection of `domain_event` optimized for human/compliance queries ("who changed this constraint and when").
- Search index and analytics warehouse are **rebuildable** from `domain_event` + relational core (no store is uniquely authoritative except the relational core).

---

## 8. Performance & Scale Strategy

| Concern | Strategy |
|---|---|
| Config reads dominate | Cache resolved values per config-version; invalidate on publish |
| Tenant-scoped queries | `tenant_id`-leading composite indexes everywhere |
| Large tenants (universities) | Partition hot tables by `tenant_id` (and by `academic_year` for archival) |
| Timetable read screens | Denormalized, rebuildable **read projections** (a "class week view" materialized for fast, offline-syncable reads) |
| Historical/archived years | Move archived academic years to cold partitions/storage; keep active hot |
| Reporting load | Runs against the analytics warehouse, never OLTP |
| Custom-field queries | Index only `is_searchable`; project hot reportable fields |
| Solver snapshots | Materialized problem snapshots stored/cached, tied to config-version (reproducible + skip recompile) |

### ADR-DB-003 — Separate OLTP and OLAP
**Rationale.** Board/government reports and platform analytics are heavy and would starve interactive scheduling if run on the primary. A CDC/event-fed warehouse isolates them. ❌ *Report off replicas of OLTP* rejected at scale (complex reports still contend and lock read replicas; schema isn't report-shaped).

---

## 9. Data Lifecycle, Residency & Retention

- **Residency:** `tenant.data_region` drives *where* Pooled/Silo data physically lives (government/international data-residency laws). Routing + Silo topology enforce it.
- **Retention:** configurable per tenant per entity class, within legal floors/ceilings (student records often have mandated retention). Retention is *policy config*, executed by lifecycle jobs.
- **Deletion/Right-to-erasure:** soft-delete for business history; hard-erasure workflows for lawful requests, reconciled with audit-retention obligations (documented conflict-resolution rules — legal holds win).
- **Archival:** completed academic years archive to cold storage but remain restorable and reportable (compliance reproducibility).

---

## 10. Migration & Schema Evolution Discipline (10-year rule)

- **Expand → Migrate → Contract** for every schema change (add nullable/new → backfill → switch reads/writes → remove old), enabling zero-downtime deploys across Pooled + N Silo stores (`MASTER_DEPLOYMENT`).
- **No destructive change without a deprecation window.** Backward compatibility is sacred (`MASTER_PRODUCT` Principle #10).
- **Config-definition changes are versioned**; removing/renaming a `setting_definition` must migrate existing `config_value`s and never orphan a live tenant's config.
- Migrations are **forward-and-backward tested** on a representative multi-segment fixture set (`MASTER_TESTING`).

---

## 11. Representative Entity-Relationship Overview (textual)

```
tenant 1─* org_unit (self-tree) 1─* learner_group *─* learner
tenant 1─* resource *─* subject (via resource_qualification)
learner_group 1─* deliverable_unit *─1 subject
deliverable_unit ─ required_resource_spec ─> resource_type
schedule 1─* assignment *─* resource (via assignment_resource)
assignment *─1 time_slot ─1 time_model ─1 tenant
schedule *─1 config_version 1─* config_value ─1 setting_definition
tenant 1─* role *─* permission (role_permission)
actor *─* role (actor_role_assignment, scoped to org_unit)
tenant 1─* constraint_definition *─1 constraint_template
every state change ──> domain_event (outbox) ──> audit_log / search / warehouse
```

---

## 12. Data-Layer Invariants (non-negotiable)

1. **Every business row has a `tenant_id`; RLS enforces isolation** even if app code errs.
2. **Uniqueness keys are tenant-scoped** (per-tenant "10-A").
3. **No double-booking is possible for published assignments** — enforced by DB constraint, not only the solver.
4. **Published schedules pin an immutable `config_version`.**
5. **Every state change produces an atomic outbox event** (no lost history).
6. **Config, custom fields, roles, hierarchy, and time-models are DATA** — adding a segment never adds a table.
7. **The relational core is authoritative; search/cache/warehouse are rebuildable.**
8. **No hard delete of business entities except lawful erasure**, which is workflow-governed and audited.

---

**END OF MASTER_DATABASE.md**
