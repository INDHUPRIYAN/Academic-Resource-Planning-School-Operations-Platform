# MASTER_PRODUCT.md
### EduFlow AI — Universal School Timetable & Academic Resource Management Platform
**Document Type:** Product Architecture — Single Source of Truth
**Document Owner:** Principal / Product Architect
**Status:** Foundational (all later documents inherit from this one)
**Version:** 1.0

---

## 0. How to Read This Document

This is the **product constitution**. Every other MASTER document (architecture, database, scheduler, backend, frontend, AI, security, testing, deployment, guidelines, roadmap) is downstream of the decisions made here. If a later document ever contradicts this one, this one wins until formally amended.

This document deliberately answers three questions in order, because getting them out of order is the single most common cause of failed ERP products:

1. **WHAT are we actually building** (the product thesis, not the feature list)
2. **WHO is it for, and what promise do we make to each of them** (personas & jobs-to-be-done)
3. **WHY is it shaped the way it is** (the product-level architecture decisions that constrain everything below)

I will repeatedly challenge our own assumptions in `⚠️ CHALLENGE` blocks and record rejected alternatives in `❌ REJECTED` blocks, because a source-of-truth document that only records the winning idea is useless — the reasoning is the asset, not the conclusion.

---

## 1. The Product Thesis

### 1.1 What we are NOT building

We are **not** building a timetable generator. This must be understood at a cellular level by everyone on the team, because 95% of "school scheduling software" in the market is a constraint-solver with a UI bolted on, and that is a commodity worth almost nothing.

A timetable generator answers: *"Given teachers, rooms, and subjects, produce a valid grid."*

That is a **feature**, not a **product**. It is table stakes. It will be one module (`MASTER_SCHEDULER.md`) inside a much larger platform, and on its own it does not create durable business value, because:

- The hard part of school operations is almost never the solve — it is the **thousand institution-specific rules** that define what "valid" even means.
- Every school believes its rules are unique (and is largely correct).
- The moment a competitor hard-codes "CBSE rules," they have locked themselves out of ICSE, State Board, colleges, and coaching centres.

### 1.2 What we ARE building

> **EduFlow AI is a configuration platform for academic operations, where the timetable is the first and most complex workload, and where every institution models its own reality — its own hierarchy, roles, terms, subjects, rules, and workflows — without a single line of source code changing.**

The core product insight, which drives the entire architecture:

> **The differences between a CBSE school, a coaching centre, and a college are DATA, not CODE.**

If that sentence is true, we win a market no one else can serve. If it is false, we've built an over-engineered timetable generator. Therefore, **the entire product is a bet on the correctness of that sentence**, and Section 4 (Configuration-as-Product) is where we prove it or break it.

### 1.3 The one-line definition

**EduFlow AI = A meta-configurable academic operations platform whose flagship capability is constraint-based scheduling, delivered as multi-tenant SaaS, that any educational institution can shape to its own workflow through configuration rather than customization.**

⚠️ **CHALLENGE: "Isn't 'configure anything' just a euphemism for 'we built nothing and made the customer do the work'?**
This is the central risk of every configurable platform (see: the graveyard of "low-code ERPs"). The answer, and the discipline this document enforces, is: **we ship strong, board-specific defaults ("Configuration Packs" — §4.5) so that 90% of schools onboard by picking a template and 10% configure deeply.** Configurability is the *ceiling*, not the *floor*. A CBSE school must be live in a day using a pack; only the unusual institution touches raw configuration. We are judged on time-to-first-timetable, not on how many knobs exist.

---

## 2. Market & Problem Space

### 2.1 The segments we must serve without a code fork

| Segment | Defining operational characteristics | Why generic tools fail them |
|---|---|---|
| **Government / State-run schools** | Huge scale, low IT literacy, offline realities, government reporting formats, free/low budget, regional languages | Cost, language, rigid reporting, no internet assumption |
| **Private K-12 (CBSE)** | Continuous & comprehensive evaluation, co-scholastic areas, section-heavy, exam-driven | Rules hard-coded to a different board |
| **Private K-12 (ICSE/ISC)** | Different subject grouping, internal assessment weighting, project-heavy | Same — hard-coded elsewhere |
| **State Boards (per-state)** | Every state differs: medium of instruction, grading, subjects, calendar | Impossible to hard-code 28+ states |
| **Matriculation / Higher Secondary** | Group/stream system (Bio-Maths, Comp-Sci, Commerce), electives | Stream logic rarely modeled |
| **International (IB / Cambridge)** | Blocks/carousels, options pools, multi-campus, multi-currency | Timetable model fundamentally different (blocks not periods) |
| **Colleges / Universities** | Credits, semesters, faculty load rules, elective enrollment, labs, department autonomy | Period-based tools can't express credit-hours & enrollment |
| **Coaching / Test-prep centres** | Batches not classes, rolling admissions, shared faculty across branches, evening slots, capacity economics | No concept of "batch," no branch-sharing of scarce faculty |
| **Future institutions (skilling, EdTech-physical, hybrid)** | Unknown | Anything hard-coded today blocks them |

### 2.2 The single unifying abstraction

For the platform to serve all of the above, we must find the **smallest set of primitives** from which every one of these realities can be *composed*. This is the most important product design act in the entire project. It is detailed in §5 (Domain Model), but stated here as thesis:

> Every institution above is ultimately **"a set of LEARNER-GROUPS that need TEACHABLE-UNITS delivered by RESOURCES into TIME-SLOTS under CONSTRAINTS, then assessed and reported."**

- "Class 10-A" (CBSE), "Batch JEE-Morning" (coaching), "CS-301 Section 2" (college) are all **Learner-Groups**.
- "Mathematics period," "Physics lab," "IB Chemistry HL block," "Reasoning session" are all **Teachable-Units / Deliveries**.
- "Teacher," "Room," "Lab equipment," "Projector," "Visiting faculty" are all **Resources**.
- Everything a school considers a "rule" is a **Constraint** over those four things.

If we model those five primitives with enough generality, everything else is configuration. This is the load-bearing wall of the product.

---

## 3. Product Principles (the non-negotiables)

These principles are the tie-breakers for every future decision. When two engineers disagree, they cite these.

1. **Configuration over Customization.** No customer gets a code branch. Ever. If a customer need can't be met by configuration, that's a gap in the configuration engine, and the fix is to generalize the engine — not to special-case the customer. *(Rationale: one codebase is the only way to serve millions of users at sustainable margin; per-customer forks are how ERP companies die of their own maintenance cost.)*

2. **The platform is opinionated at the template layer, unopinionated at the engine layer.** The engine can express almost anything; the templates (Configuration Packs) make the common case one click. This resolves the "configurable = empty" trap.

3. **Multi-tenant by default, isolatable on demand.** Shared infrastructure for margin; hard data isolation for trust and for regulated/government tenants. *(Detailed in MASTER_ARCHITECTURE & MASTER_SECURITY.)*

4. **The timetable is a workload, not the product.** The scheduling engine is a pluggable module that operates on the domain primitives; it must never leak its assumptions into the core domain.

5. **Offline & low-connectivity is a first-class citizen, not a degraded mode.** Government and rural schools are a core segment, not an edge case. This shapes the frontend (local-first where needed) and API design.

6. **Every tenant's data model is versioned and auditable.** Because tenants configure their own reality, we must be able to answer "what did this school's rules look like on the day this timetable was generated?" — configuration is versioned like code.

7. **Explainability over magic.** Especially for AI (`MASTER_AI.md`): when the system proposes a timetable or flags a conflict, it must say *why*. Administrators will not trust — and cannot defend to their principal — a black box.

8. **Progressive disclosure.** A first-time government-school clerk and a university registrar use the same product. The clerk must never see credit-hour configuration; the registrar must be able to reach it. Complexity is revealed on demand.

9. **Localization is structural, not cosmetic.** Language, script, calendar (including regional/lunar academic calendars), number formats, and reporting formats are configuration, not an afterthought translation pass.

10. **Backward compatibility is sacred.** A 10-year document implies 10 years of tenants. A config or schema change must never silently break an existing tenant's saved configuration or historical records.

---

## 4. Configuration-as-Product (the core innovation)

This section is the differentiator. It defines *how* an institution shapes the platform. It must be read alongside `MASTER_DATABASE.md` (how config is stored) and `MASTER_BACKEND.md` (how config is evaluated).

### 4.1 The layered configuration model

Configuration is not one flat settings screen. It is a **layered inheritance stack**, resolved top-down, each layer able to override the one above (subject to locks):

```
PLATFORM DEFAULTS        (shipped by us, the safe baseline)
   ▼ overridden by
CONFIGURATION PACK       (board/segment template: "CBSE K-12", "TN State", "Coaching")
   ▼ overridden by
TENANT (Institution)     (this specific school group)
   ▼ overridden by
CAMPUS / BRANCH          (one physical location of the tenant)
   ▼ overridden by
ACADEMIC PROGRAM         (K-12 wing vs. Jr College wing in same campus)
   ▼ overridden by
ACADEMIC YEAR / TERM     (this year's rules may differ from last year's)
   ▼ overridden by
LEARNER-GROUP            (Class 10-A may have a rule 10-B doesn't)
```

**Resolution rule:** the effective value of any setting for any entity is computed by walking this stack from the entity upward and taking the nearest defined value, unless a higher layer has marked the setting `locked` (then the locked value wins — this is how a government body or head office enforces policy campuses cannot override).

⚠️ **CHALLENGE: Isn't a 7-layer inheritance stack going to be an undebuggable nightmare?**
Yes, if we expose it naively. Mitigations, which are *product requirements* not nice-to-haves: (a) every effective setting screen shows a **"why this value?" trace** revealing which layer set it; (b) config resolution is a pure, cached function with a visible provenance chain; (c) 95% of layers are empty for a typical tenant — the stack is *capacity*, and most tenants use Pack → Tenant only. We accept the complexity because the alternative (flat config) cannot express "head office sets a rule all 40 branches must obey, except branch 7 which regulators exempted."

❌ **REJECTED: Flat per-tenant config.** Simple, but cannot model multi-campus chains, franchise coaching networks, or government mandates that flow down to schools. Rejected because it fails three of our nine segments.

❌ **REJECTED: Full code-level plugin per tenant.** Maximally flexible, but violates Principle #1 and destroys margin. Rejected.

### 4.2 What is configurable (the configuration surface)

The platform exposes these configuration domains. Each is defined precisely in later documents; here we assert *that they are data, not code*:

- **Institutional hierarchy** — how many levels (Group → Campus → Program → Grade → Section, or Chain → Branch → Batch). The *depth and names of the hierarchy itself* are configurable.
- **Roles & permissions** — not a fixed enum. A tenant defines roles ("Vice-Principal," "Timetable In-charge," "HOD-Science") and the permissions each holds. (See `MASTER_SECURITY.md` — attribute/relationship-based access.)
- **Academic calendar** — terms, semesters, working days, holidays, day-types (odd/even day cycles, rotating timetables), regional calendars.
- **Time model** — periods vs. blocks vs. credit-hours vs. free-form slots. This is a *pluggable time strategy*, because a period-school and a college are fundamentally different here.
- **Subject/curriculum model** — subjects, electives, streams/groups, options pools, co-scholastic areas, credits.
- **Resource types** — the *types* of resources are configurable (a coaching centre has "shared visiting faculty"; a college has "lab with 30 seats + specific equipment").
- **Constraints & rules** — the heart of it. A tenant composes rules from a **constraint vocabulary** (§4.3).
- **Workflows** — approval chains (who approves a timetable, a leave, a substitution), configurable as state machines.
- **Assessment & grading** — grading scales, weighting, report card formats.
- **Forms & fields** — tenants can add custom fields to core entities (a "UDISE code" for govt schools, a "batch fee tier" for coaching). Custom fields are first-class, typed, validated, reportable.
- **Reports & documents** — templated, tenant-brandable, format-configurable (govt reporting formats, board formats).
- **Localization** — language, script, direction, calendar, formats.
- **Notifications** — channels (SMS/WhatsApp/email/push/in-app) and triggers.

### 4.3 The Constraint Vocabulary (product concept, engine in MASTER_SCHEDULER)

Rather than hard-coding rules like "a teacher cannot be in two rooms at once," we ship a **vocabulary of constraint primitives** that tenants compose. Conceptually:

- **Hard constraints** (must never be violated): resource single-occupancy, learner-group single-occupancy, capacity, availability windows, dependency (lab after lecture), locked assignments.
- **Soft constraints** (preferences, weighted, optimized): teacher preferred slots, minimize gaps, spread subjects across week, avoid heavy subjects in last period, balance teacher daily load, group double-periods.
- **Meta / policy constraints**: max consecutive teaching hours (labor law / union rules), minimum breaks, workload caps, gender/staffing policies, government-mandated instructional minutes per subject.

The **product promise** is that a tenant expresses a rule in near-natural terms ("Science labs must be in the morning," "No teacher teaches more than 3 periods in a row," "Class 10 must get 6 Maths periods/week") and the system compiles it into engine constraints. This is where the AI layer (`MASTER_AI.md`) earns its place: **natural-language-to-constraint translation** with a human confirmation step. Never silent.

⚠️ **CHALLENGE: If tenants can write arbitrary constraints, they'll create unsatisfiable rule sets and blame us.**
True and important. Product requirements that follow from this: (a) a **constraint linter** that detects contradictions *before* solving ("you require 8 Maths periods but only allocated 5 slots"); (b) when a solve fails, the engine returns a **minimal conflicting set** ("these 3 rules cannot all hold — relax one"), never just "no solution"; (c) soft/hard classification so the system can produce a *best-effort* timetable with an explicit list of unmet preferences. Explainability (Principle #7) is what makes configurable constraints safe.

### 4.4 Configuration is versioned & governed

- Every configuration change is an **event** with author, timestamp, before/after, and reason.
- Configurations have **draft → review → published** states (a configurable workflow itself).
- A published timetable **pins the configuration version** it was generated under, so history is reproducible.
- Configuration can be **exported/imported** (a school district can push a standard config to 200 schools).

### 4.5 Configuration Packs (the go-to-market accelerant)

A **Configuration Pack** is a curated, versioned bundle of defaults for a segment: hierarchy shape, roles, calendar template, subject lists, standard constraints, report formats, and localization.

- We ship and maintain first-party packs: `CBSE-K12`, `ICSE-K12`, `TN-State`, `Maharashtra-State`, `IB-PYP/MYP/DP`, `Cambridge`, `Indian-College-Semester`, `Coaching-JEE/NEET`, `Government-UDISE`.
- Packs are **starting points**, fully overridable.
- Packs are versioned; a tenant can adopt a pack, then diverge, and still receive pack *updates* as suggested (non-destructive) merges.
- **This is how we escape the configurability trap:** the median customer never configures from scratch.

Third-party / partner packs are a future marketplace (`MASTER_FUTURE_ROADMAP.md`).

---

## 5. Domain Model (product-level; formal schema in MASTER_DATABASE)

The primitives, named canonically. Every team uses these exact terms.

| Primitive | Definition | Segment-specific manifestations |
|---|---|---|
| **Tenant** | An institution or institution-group that owns data & config. | A school, a school chain, a coaching network, a university. |
| **Org Unit** | A configurable node in the institutional hierarchy. | Group, Campus/Branch, Program/Wing, Department. |
| **Learner-Group** | The unit that receives scheduled delivery together. | Class-Section, Batch, Course-Section, Stream cohort. |
| **Learner** | An individual student/enrollee (Phase 2+ for full SIS). | Student, batch enrollee, college student. |
| **Deliverable-Unit** | A teachable thing that consumes time. | Subject-period, Lab, Block, Credit-course, Session. |
| **Resource** | Anything scarce that a delivery consumes. | Teacher, Room, Lab, Equipment, Visiting faculty. |
| **Time-Model** | The pluggable strategy for how time is divided. | Periods, Blocks, Credit-hours, Free slots. |
| **Time-Slot** | A concrete bookable interval in the calendar. | Period 3 on Monday; Tue 14:00–15:30 block. |
| **Assignment** | A binding of {Deliverable + Resource(s) + Learner-Group + Time-Slot}. | The atom of a timetable. |
| **Constraint** | A rule over assignments. | Hard/soft/policy (see §4.3). |
| **Schedule / Timetable** | A validated, published set of Assignments over a period. | Class TT, Teacher TT, Room TT, Exam TT. |
| **Workflow** | A configurable state machine over an entity. | Approval, substitution, leave. |
| **Actor** | A human/system principal with tenant-defined roles. | Admin, teacher, HOD, parent, student, integration. |

**Key product decision:** these primitives are **stable**; the *configuration* of them is what varies. We will resist every future temptation to add a segment-specific primitive (e.g., "CoachingBatch") when configuration of an existing primitive suffices.

⚠️ **CHALLENGE: Is "Learner-Group" too abstract? Won't users be confused seeing "Learner-Group" in the UI?**
Correct — abstraction is for the *engine and data model*, never for the user. The UI always uses the tenant's *own vocabulary* (label mapping is configuration): a CBSE user sees "Section," a coaching user sees "Batch." The abstract term never surfaces. This label-mapping requirement is a product mandate on the frontend.

---

## 6. Personas & Jobs-To-Be-Done

Each persona gets a distinct experience over the *same* platform (Principle #8). The promise we make to each:

### 6.1 Super-Admin (Platform operator — us)
- Manage tenants, packs, platform health, billing, global feature flags.
- **JTBD:** onboard a new school in minutes; roll out a new state's pack; monitor SLA.

### 6.2 Tenant Administrator (Principal / Owner / Registrar)
- Owns institutional configuration and high-level governance.
- **JTBD:** "Get my school live and generate this term's timetable"; "prove compliance to the board"; "control who can change what."
- **Promise:** you never touch code; a pack + a guided setup wizard gets you live; you can always see *why* the system did what it did.

### 6.3 Timetable In-charge / Academic Coordinator
- The power user of the scheduler.
- **JTBD:** define constraints, run generation, resolve conflicts, publish, handle daily substitutions.
- **Promise:** when generation fails, you get a *fixable explanation*, not a dead end; daily reality (a teacher is absent) is a two-click substitution that respects all constraints.

### 6.4 HOD / Department Head
- Owns a department's subjects, teacher loads, and lab needs.
- **JTBD:** balance teacher workload; ensure lab access; approve within their scope.
- **Promise:** you see and act only within your department (scoped access), with clear workload visibility.

### 6.5 Teacher
- Consumer of the schedule + light interaction.
- **JTBD:** "what's my day/week"; "request a swap/leave"; "mark a substitution"; low-friction, mobile, offline-tolerant.
- **Promise:** your timetable in your pocket, works with bad signal, notifies you of changes.

### 6.6 Student / Parent
- Read-mostly consumer.
- **JTBD:** "what's my child's schedule / exam TT / room / any changes today."
- **Promise:** always-current, in your language, on your phone.

### 6.7 Government / Board Auditor (external, read-scoped)
- **JTBD:** verify compliance and pull mandated reports.
- **Promise:** scoped, auditable, format-correct exports — without giving them write access or seeing other tenants.

### 6.8 Integration / System actor
- Other systems (fee, LMS, biometric attendance, SIS).
- **JTBD:** read/write via stable APIs, webhooks on change.
- **Promise:** versioned, documented, rate-limited APIs; events, not polling.

⚠️ **CHALLENGE: Are we scope-creeping into a full SIS/LMS/ERP?**
Real risk. **Product boundary (v1–v2):** EduFlow AI owns **scheduling + academic resource + the configuration/identity/reporting substrate** that scheduling requires. Full fee management, full LMS content, and full HR/payroll are **integration targets, not build targets**, in the near term — but the *configuration substrate and domain model are designed so those modules could be added later without re-architecture* (see roadmap). We say "no" to building them now, "yes" to not blocking them. This boundary is a product commitment, revisited only in `MASTER_FUTURE_ROADMAP.md`.

---

## 7. Core Product Capabilities (v1 scope)

Grouped by module. Detailed behavior lives in the module's MASTER doc; this is the authoritative *scope list*.

### 7.1 Onboarding & Configuration
- Pack selection + guided setup wizard (progressive disclosure).
- Hierarchy builder, role/permission designer, calendar builder.
- Custom fields, label mapping, localization setup.
- Config draft/review/publish + versioning + import/export.

### 7.2 Academic Data Management
- Subjects/curriculum, streams/electives, learner-groups, resources (teachers/rooms/labs/equipment), teacher qualifications & availability, capacities.

### 7.3 Scheduling Engine (flagship)
- Constraint definition (vocabulary + NL assist), linting, generation, multi-solution comparison, conflict explanation, manual override with live validation, publish with version pinning. (Full spec: `MASTER_SCHEDULER.md`.)

### 7.4 Timetable Consumption
- Class / teacher / room / student / exam views; per-persona; multi-format export (PDF, print, calendar feed); real-time change propagation.

### 7.5 Daily Operations
- Substitution management (teacher absent → constraint-aware suggestions), leave workflow, ad-hoc changes, event/holiday injection, room reallocation.

### 7.6 Assessment & Reporting (scheduling-adjacent v1, deeper later)
- Exam timetabling, grading scales config, report templates, compliance/board/govt reports, exports.

### 7.7 Communication
- Multi-channel notifications on relevant events (TT published, changed, substitution assigned, leave decided).

### 7.8 Platform Services (cross-cutting)
- Identity & access (tenant-defined RBAC/ABAC), audit trail, search, files/documents, jobs (async generation), observability.

**Explicitly OUT of v1** (documented so no one assumes them): full LMS content delivery, fee/payment processing, HR/payroll, transport/route optimization, hostel/mess, library circulation. All are future modules or integrations (`MASTER_FUTURE_ROADMAP.md`).

---

## 8. Product-Level Non-Functional Requirements

These are *product promises* with numbers; engineering docs must honor them.

| Dimension | Target | Why |
|---|---|---|
| **Time-to-first-timetable** | < 1 day for a pack-based school; < 2 hrs for a small coaching centre | Onboarding is the #1 churn point in ERP. |
| **Scale** | 100k+ tenants; millions of daily active consumers; tenants from 1 to 500 org-units | The "millions of users" mandate. |
| **Generation performance** | A typical K-12 school (≈40 groups, ≈60 teachers) solves in seconds-to-low-minutes; large college async with progress | Users won't wait 30 min staring at a spinner. |
| **Availability** | 99.9% for consumption; scheduled windows for heavy jobs | Teachers/parents check daily. |
| **Offline tolerance** | Core consumption works offline; sync on reconnect | Government/rural mandate. |
| **Localization** | Multi-language, multi-script, multi-calendar from day one | Core segments are non-English-first. |
| **Data isolation** | Strict per-tenant; optional dedicated isolation for govt | Trust + regulation. |
| **Auditability** | Every config & schedule change traceable | Compliance + reproducibility (Principle #6). |
| **Explainability** | Every rejection/suggestion has a human-readable reason | Trust (Principle #7). |

---

## 9. Product Risks & Mitigations (the honest section)

| Risk | Severity | Mitigation (which document owns it) |
|---|---|---|
| Configurability becomes "we built nothing" | **Critical** | Configuration Packs + setup wizard + strong defaults (§4.5, this doc) |
| Constraint sets become unsatisfiable / users blame us | High | Linter + minimal-conflict-set + soft/hard split + explainability (MASTER_SCHEDULER) |
| 7-layer config becomes undebuggable | High | Provenance trace, caching, most layers empty (§4.1) |
| Abstraction leaks into UI, confusing users | Medium | Tenant vocabulary label-mapping mandate (§5, MASTER_FRONTEND) |
| Scope creep into full ERP | High | Firm v1 boundary; substrate-ready, not built (§6, MASTER_FUTURE_ROADMAP) |
| Multi-tenant data leakage | **Critical** | Isolation by design (MASTER_SECURITY, MASTER_ARCHITECTURE) |
| AI proposes wrong constraints/timetables silently | High | Human-in-the-loop confirmation, explainability (MASTER_AI) |
| Offline sync conflicts corrupt schedules | High | Local-first strategy + conflict resolution (MASTER_FRONTEND, MASTER_BACKEND) |
| Government reporting formats change | Medium | Reports as configurable templates, not code (§4.2) |
| Backward-incompatible schema/config change breaks tenants | High | Versioning + migration discipline (MASTER_DATABASE, MASTER_CODING_GUIDELINES) |

---

## 10. Success Metrics (how we know the product is working)

- **Activation:** % of new tenants that publish a first timetable within 1 day.
- **Configuration self-service rate:** % of tenants live *without* our services team touching config.
- **Solve success rate:** % of generation runs producing an accepted timetable without manual escalation.
- **Explainability satisfaction:** when a solve fails, % of users who resolve it themselves using the conflict explanation.
- **Segment coverage:** number of distinct segments live on a *single codebase* (the core thesis, measured).
- **Consumption engagement:** DAU/WAU of teachers/parents (proves the platform is used, not just installed).
- **Config-fork count:** must remain **zero** (a non-zero value means we violated Principle #1 — a red alert).

---

## 11. Glossary (canonical terms — used identically in all documents)

- **Tenant** — an institution/group that owns isolated data and config.
- **Org Unit** — a configurable node in a tenant's hierarchy.
- **Learner-Group** — the cohort that receives scheduled delivery together (UI-labeled per tenant).
- **Deliverable-Unit** — a teachable, time-consuming unit.
- **Resource** — a scarce thing a delivery consumes (teacher/room/lab/equipment).
- **Time-Model** — pluggable strategy for dividing time (periods/blocks/credits/free).
- **Assignment** — the atomic {deliverable + resource(s) + group + slot} binding.
- **Constraint** — a hard/soft/policy rule over assignments.
- **Configuration Pack** — a versioned segment template of defaults.
- **Configuration Stack** — the 7-layer inheritance from Platform Defaults down to Learner-Group.
- **Provenance Trace** — the "why this value?" explanation of an effective setting.
- **Constraint Vocabulary** — the composable set of rule primitives.
- **Minimal Conflicting Set** — the smallest group of rules that together cause an unsolvable schedule.

---

## 12. What each downstream document must inherit from this one

| Document | Must honor |
|---|---|
| MASTER_ARCHITECTURE | Multi-tenancy, config-as-data, module boundaries, offline-first, scheduler-as-pluggable-workload |
| MASTER_DATABASE | Domain primitives (§5), 7-layer config storage, versioning, custom fields, tenant isolation |
| MASTER_SCHEDULER | Constraint vocabulary (§4.3), hard/soft split, linter, minimal-conflict-set, explainability, time-model plugins |
| MASTER_BACKEND | Config resolution engine, workflow state machines, event/audit model, API versioning |
| MASTER_FRONTEND | Progressive disclosure, tenant vocabulary label-mapping, per-persona UX, offline consumption, provenance UI |
| MASTER_AI | NL-to-constraint with human confirmation, explainability, never-silent principle |
| MASTER_SECURITY | Tenant isolation, tenant-defined RBAC/ABAC, audit, scoped external auditors |
| MASTER_TESTING | Config-matrix testing across segments, solver correctness, backward-compat guarantees |
| MASTER_DEPLOYMENT | Multi-tenant + optional isolated deploy, pack rollout, zero-downtime migrations |
| MASTER_CODING_GUIDELINES | No config-forks rule, backward-compat discipline, domain vocabulary |
| MASTER_FUTURE_ROADMAP | v1 boundary respected; substrate-ready extensions (SIS/LMS/fee) |

---

**END OF MASTER_PRODUCT.md**
