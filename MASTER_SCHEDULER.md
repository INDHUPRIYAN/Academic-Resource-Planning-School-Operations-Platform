# MASTER_SCHEDULER.md
### EduFlow AI — Scheduling Engine Architecture
**Document Type:** Engine Architecture — Single Source of Truth
**Inherits from:** MASTER_PRODUCT.md, MASTER_ARCHITECTURE.md, MASTER_DATABASE.md
**Version:** 1.0

---

## 0. Purpose & Position

This document specifies the **flagship workload**: the constraint-based scheduling engine. Per `MASTER_PRODUCT` Principle #4, the scheduler is a **pluggable workload, not the product** — it operates on the domain primitives and never leaks its assumptions into the core.

It answers: how do we take a tenant's *configured* groups, resources, time-model, and constraints and produce **valid, explainable, optimized** timetables — for a period-based CBSE school, a block-based IB school, a credit-based college, and a batch-based coaching centre — **with one engine**?

The engine's contract is set by `MASTER_ARCHITECTURE ADR-003` (stateless, async, self-contained job, cancellable, reproducible).

---

## 1. The Scheduling Problem, Stated Honestly

Timetabling is **NP-hard** (a generalization of graph coloring + bin packing + assignment). There is no fast, always-optimal algorithm. This truth drives every decision here:

- We will **not** promise "the optimal timetable." We promise a **valid** timetable (all hard constraints met) that is **good** (soft constraints optimized as far as time allows) and, crucially, **explainable** when it can't be produced.
- We will design for the **common case** (a K-12 school solves in seconds-to-minutes, `MASTER_PRODUCT §8`) while degrading gracefully for the pathological case (a 500-group university → partition + async + progress).

⚠️ **CHALLENGE: Should we even build a solver, or license one?** We build the **modeling, compilation, explanation, and orchestration** layers (our IP and our differentiator) and stand on a **mature constraint-programming/optimization library** for the raw search (`MASTER_ARCHITECTURE §9` permits a different runtime for the scheduler). Reinventing a CP-SAT solver is a multi-year distraction; our value is the *configurable modeling and explainability*, not the search kernel.

---

## 2. The Time-Model Abstraction (how one engine serves all segments)

The reason competitors can't serve every segment is that they hard-code "periods." We abstract time into **pluggable Time-Model strategies**, each compiling into the same underlying variable structure.

| Time-Model | Segment | How time is represented | Solver sees |
|---|---|---|---|
| **Period** | K-12 (CBSE/ICSE/State) | Fixed daily periods × day-types | Discrete slots per group/day |
| **Block** | IB / Cambridge | Longer blocks, carousels, option pools | Grouped slots, option-set membership |
| **Credit-Hour** | Colleges/universities | Courses need N credit-hours/week, flexible placement | Variable-length demand over a week grid |
| **Free-Slot** | Coaching / hybrid | Arbitrary start/end sessions, evening/weekend | Continuous-ish grid discretized to granularity |

### ADR-SCH-001 — Time-Models compile to a common "slot-demand-resource" internal representation

**Decision.** Every time-model is a **compiler** from tenant configuration into a **canonical internal problem**: a set of **decision variables** ("which slot(s) does this delivery occupy, using which resources"), a **discretized time grid**, **demands** (deliverable-units needing placement), and **resources** with availability.

**Rationale.** The search kernel should never know whether it's solving "periods" or "credits." Only the front-of-engine compiler differs per model; the kernel and the explainer are shared. This is the architectural move that makes "one engine, all segments" true.

**Consequences.** Adding a future institution type may mean a new *time-model compiler* (a bounded, well-defined extension point) — never a rewrite of the solver. This satisfies `MASTER_PRODUCT` Principle (future expansion without source change for existing paths).

---

## 3. The Constraint System

Realizes `MASTER_PRODUCT §4.3` (Constraint Vocabulary) and `MASTER_DATABASE §2.6` (constraints stored as data).

### 3.1 Constraint taxonomy

**Hard constraints** (violation = invalid schedule; must hold):
- **Single-occupancy:** a resource (teacher/room) is in ≤1 place per slot.
- **Group single-occupancy:** a learner-group attends ≤1 delivery per slot.
- **Capacity:** group size ≤ room capacity; batch size ≤ seat count.
- **Availability:** deliveries only in resource/group available windows.
- **Qualification:** only qualified resources deliver a subject.
- **Dependency/ordering:** lecture before lab; prerequisite sequencing.
- **Locked assignments:** manually pinned placements are inviolable.
- **Required frequency:** N sessions/week or M credit-hours must be placed.

**Soft constraints** (weighted preferences; optimize, don't require):
- Teacher preferred/avoided slots; minimize teacher gaps; balance daily teaching load.
- Spread a subject across the week (not 3 Maths on one day).
- Heavy subjects earlier; PE/labs at suitable times.
- Group double-periods where pedagogically wanted; minimize learner idle gaps.
- Room stability (a group stays in "its" room where possible).

**Policy/meta constraints** (often hard, but institution/law-driven):
- Max consecutive teaching hours (labor law / union rules).
- Minimum breaks between sessions; max daily load.
- Government-mandated instructional minutes per subject.
- Staffing/coverage policies.

### 3.2 Constraints are composed from templates, not coded

A tenant's rule = an instance of a **`constraint_template`** (platform vocabulary) with **typed parameters** and a **scope** (which groups/resources). The engine has a **handler per template** that knows how to translate that instance into solver terms for the current time-model. Adding a genuinely new *kind* of rule = a new template + handler (platform-level, rare); expressing a school's rule = configuration (common).

### ADR-SCH-002 — Hard/Soft/Policy separation with explicit weights is mandatory
**Rationale.** It enables (a) best-effort schedules when preferences conflict, (b) meaningful "why not perfect?" explanations, and (c) tenant control over trade-offs (this school values teacher-gaps-minimization over room-stability; that one is opposite — a *weight configuration*). Without this split, every conflict becomes a hard failure and the product feels broken.

---

## 4. The Engine Pipeline

A solve is a pipeline, each stage independently testable (`MASTER_TESTING`):

```
 (1) MATERIALIZE ─> (2) COMPILE (time-model) ─> (3) LINT ─> (4) SOLVE
        ─> (5) EXPLAIN ─> (6) RANK/COMPARE ─> (7) RETURN candidates
```

### 4.1 Materialize
The core (not the solver) builds a **self-contained problem snapshot** (`MASTER_ARCHITECTURE ADR-003`): groups, deliverable-units, resources + availability + qualifications, the time grid, all constraint instances, and the pinned `config_version`. The snapshot is **immutable and reproducible** (same snapshot → same result), stored for caching and audit.

### 4.2 Compile
The tenant's **time-model compiler** converts the snapshot into the canonical internal representation (decision variables, domains, constraint expressions). This is where period/block/credit/free differences are absorbed.

### 4.3 Lint (before wasting a solve)
The **Constraint Linter** statically detects impossibility *before* search (`MASTER_PRODUCT §4.3` challenge mitigation):
- **Arithmetic infeasibility:** "Class 10 requires 8 Maths sessions but the week has only 6 free group-slots after other demands."
- **Resource starvation:** "3 groups need the single Chem-lab in period 1 — impossible."
- **Contradictory rules:** "Rule A pins Physics to period 1; Rule B forbids Science before period 3."
- **Qualification gaps:** "No qualified teacher exists for IB-HL-Chemistry."

The linter returns human-readable problems **with the offending config identified** so users fix inputs, not stare at a failed solve. This is a primary trust mechanism.

### 4.4 Solve
The search kernel (mature CP-SAT/optimization library) explores the space:
- **Hard constraints** as model constraints (must satisfy).
- **Soft constraints** as a **weighted objective** to minimize violation cost.
- **Time-boxed** with a CPU/wall budget (`ADR-003` cancellable); returns the best-found within budget.
- Emits **progress + intermediate solutions** via events (live UI feedback, `MASTER_ARCHITECTURE §5.3`).

### ADR-SCH-003 — Constraint Programming (CP-SAT-style) as the primary kernel, with heuristics as fallback
**Decision.** Primary kernel is **constraint programming** (excellent for hard-constraint feasibility + optimization on discrete scheduling). For very large or time-pressured cases, a **metaheuristic** (large-neighborhood/local search, simulated-annealing-style improvement over a feasible seed) provides "good enough fast."
**Alternatives.**
- ❌ *Pure genetic algorithm.* Poor at guaranteeing hard-constraint feasibility; hard to explain. Rejected as primary.
- ❌ *Pure greedy/heuristic.* Fast but gets stuck; can't optimize globally; weak feasibility guarantees. Rejected as sole method.
- ❌ *MILP only.* Powerful but can be slow/opaque for this shape and harder to explain. Rejected as primary; may assist specific subproblems.
- ✅ *CP-first, metaheuristic-assist.* Chosen — feasibility + explainability from CP, speed at scale from heuristics.

### 4.5 Explain (the differentiator)
Whatever the outcome, the engine **explains**:
- **On success-with-tradeoffs:** "All hard rules met. Unmet preferences: 3 teacher-gap goals (cost 12), 1 room-stability goal — because the Chem-lab is a bottleneck period 3–4."
- **On failure:** the **Minimal Conflicting Set** — the *smallest* group of hard constraints that cannot co-hold ("These 3 rules conflict; relax one: …"). Computed via unsat-core extraction / iterative constraint relaxation. **Never** "no solution found."
- **On any assignment:** "Why is Physics here?" → the chain of constraints that forced/preferred it.

### ADR-SCH-004 — Explanations are a first-class engine output, not a debugging afterthought
**Rationale.** `MASTER_PRODUCT` Principle #7 (explainability over magic). An administrator must defend the timetable to a principal and fix a failed solve themselves (a Success Metric). The engine therefore *always* returns structured reasons, and the AI layer (`MASTER_AI`) renders them in natural language. A solver that only returns SAT/UNSAT is unacceptable for this product.

### 4.6 Rank / Compare
The engine returns **multiple candidate schedules** (e.g., top-N by objective, or contrasting trade-offs: "Option A minimizes teacher gaps; Option B maximizes room stability"). The coordinator compares and picks (`MASTER_PRODUCT §7.3`). Candidates are stored as `schedule` rows (`MASTER_DATABASE §2.5`).

### 4.7 Return
Candidates + explanations flow back via events; the core persists them (proposed status), the coordinator reviews, edits (with live re-validation), and publishes (pinning config-version).

---

## 5. Scale Strategy: Partitioning & Incrementality

A 500-group university cannot be one monolithic solve in reasonable time. Two techniques:

### 5.1 Problem partitioning
**Independent sub-problems solve separately.** If Department A shares no resources, rooms, or teachers with Department B, they are independent and solved in parallel. The **materialize** stage builds a **resource-sharing graph**; connected components are solved independently, then composed. This turns one huge NP-hard problem into many small ones.

### 5.2 Incremental / warm-start solving
Daily reality changes little. When a small edit occurs (a teacher leaves, one room closes), we **re-solve incrementally** from the existing solution (fix the untouched majority, re-search only the affected neighborhood) rather than from scratch. Substitutions (§6) are the extreme case.

### ADR-SCH-005 — Partition-then-solve for large tenants; incremental re-solve for edits
**Rationale.** Keeps the common case fast and makes the pathological case tractable, without a different engine. ❌ *Always full-solve* rejected (unusable at university scale; wasteful for tiny edits).

---

## 6. Daily Operations: Substitution & Change Engine

Substitutions are the **most-used** scheduling feature (a teacher is absent *today*). This is a **constrained sub-solve**, not a manual scramble.

- **Trigger:** teacher marked absent / room closed / event injected.
- **Engine action:** find valid replacement resources that (a) are qualified, (b) are free that slot, (c) don't breach policy (max consecutive load), (d) minimize disruption — ranked suggestions with reasons ("Ms. Rao: qualified, free, +1 to her daily load").
- **Output:** ranked substitution options; coordinator one-click applies; change recorded as `schedule_change` (`MASTER_DATABASE §2.5`) over the published schedule **without regenerating** the whole timetable.
- **Notifications** fire to affected teacher/group/parents (`MASTER_ARCHITECTURE §5`).

This is incremental solving (§5.2) applied to a single slot, and it is where users feel the platform's daily value.

---

## 7. Manual Override with Live Validation

Coordinators must be able to **hand-tweak** ("put Sports last period Friday"). Every manual edit is **validated live** against hard constraints; the UI shows violations instantly (`MASTER_FRONTEND`). A manual pin becomes a **locked assignment** (hard constraint) that subsequent (re)solves respect. The human is always in control; the engine guards correctness.

---

## 8. Exam Timetabling (reuses the engine)

Exams are a scheduling problem with different constraints (no student sits two exams at once, invigilator assignment, room capacity for spaced seating, exam-gap preferences). It reuses the **same engine** with an exam-flavored constraint set and time-model — proving the abstraction's generality. Not a separate codebase.

---

## 9. Reproducibility, Caching & Determinism

- A solve is defined by `(problem_snapshot, engine_version, random_seed)`. Fixing the seed + snapshot yields a **reproducible** result (audit, `MASTER_PRODUCT` Principle #6).
- Snapshots and results are cached; re-requesting an unchanged problem returns instantly.
- `engine_version` is recorded on every `schedule` so we can explain historical results even after the engine evolves (10-year rule).

---

## 10. Performance Targets & Budgets

| Case | Target | Method |
|---|---|---|
| Small coaching (≤10 batches) | seconds | direct CP solve |
| Typical K-12 (~40 groups, ~60 teachers) | seconds–low minutes | CP solve, possibly partitioned |
| Large school (100+ groups) | minutes, async w/ progress | partition + CP + heuristic polish |
| University (500+ groups) | async, progress-streamed | partition into components, parallel solve, compose |
| Single substitution | sub-second suggestions | incremental neighborhood solve |
| Manual-edit validation | instant (<100ms) | in-memory constraint check, not full solve |

CPU/time budgets are **tenant-tier-aware config**; runaway solves are cancelled and explained.

---

## 11. Engine Extensibility (future-proofing)

Bounded, well-defined extension points (never core rewrites):
- **New Time-Model** → new compiler implementing the canonical-representation contract.
- **New Constraint kind** → new `constraint_template` + handler.
- **New objective/optimization goal** → new weighted soft-constraint handler.
- **New solve strategy** → pluggable kernel behind the same pipeline contract.

Each is a documented interface; existing tenants are unaffected when new ones are added (`MASTER_PRODUCT` Principle #10).

---

## 12. Engine Invariants (non-negotiable)

1. **A returned schedule never violates a hard constraint** — and the DB double-checks (`MASTER_DATABASE §6.1`).
2. **The engine never blocks the interactive path** — always async via job/events (`ADR-003`).
3. **Every solve is reproducible** from its snapshot + engine version + seed.
4. **Failure always yields a Minimal Conflicting Set**, never a bare "no solution."
5. **The search kernel is time-model-agnostic**; only compilers differ per segment.
6. **Explanations are always produced** for success-with-tradeoffs and for failure.
7. **Manual pins are inviolable** in subsequent solves.
8. **Adding a segment adds a compiler or template, never a new engine.**

---

**END OF MASTER_SCHEDULER.md**
