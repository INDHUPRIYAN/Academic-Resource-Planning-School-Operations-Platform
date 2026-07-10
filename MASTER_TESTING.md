# MASTER_TESTING.md
### EduFlow AI — Testing & Quality Architecture
**Document Type:** QA Architecture — Single Source of Truth
**Inherits from:** ALL prior MASTER documents
**Version:** 1.0

---

## 0. Purpose & The Central Testing Challenge

This document defines how we prove the platform **works and keeps working for 10 years across every segment**. The testing strategy has one dominant, unusual challenge that shapes everything:

> **We ship one codebase that behaves differently for every tenant based on configuration. Therefore we don't test "the app" — we test "the app across a matrix of configurations."**

A green test suite on the default config proves almost nothing; a CBSE-passing build can be broken for a coaching centre. **Configuration-matrix testing (§4)** is the defining QA innovation of this platform.

Two further high-stakes correctness domains demand special rigor:
- **The solver** must produce *provably valid* schedules (`MASTER_SCHEDULER`).
- **Tenant isolation** must *never* leak (`MASTER_SECURITY`).

---

## 1. Testing Principles

1. **Test behavior, not implementation** — so we can refactor freely for 10 years.
2. **The test pyramid holds** — many fast unit tests, fewer integration, fewest E2E — but topped by the **configuration matrix** (a horizontal axis across all levels).
3. **Correctness domains get exhaustive rigor** — solver validity and tenant isolation are tested adversarially, not just happily.
4. **Backward compatibility is a tested guarantee** — not a hope (Principle #10).
5. **Determinism is testable** — reproducible solves and pure config resolution enable golden-master testing.
6. **Every bug becomes a regression test** — the suite only grows.
7. **Performance and scale are tested, not assumed** — against the NFR targets (`MASTER_PRODUCT §8`).

---

## 2. The Test Pyramid (levels)

### 2.1 Unit tests (broadest base)
- **Domain logic** in each module, framework-free (clean layering, `MASTER_BACKEND §2.1`), fast, isolated.
- **Config resolution** as a **pure function** → ideal for exhaustive unit testing of the 7-layer stack + locks + provenance.
- **Constraint template handlers** — each handler tested for correct compilation to solver terms.
- **Time-model compilers** — each (period/block/credit/free) tested independently.

### 2.2 Integration tests
- Module-to-module through **public interfaces only** (never internal tables — mirrors the enforced boundaries, `MASTER_BACKEND ADR-BE-002`).
- DB integration with **row-level security on** (isolation tested at the data layer, not mocked away).
- Outbox/event flow: a write produces exactly the right event, consumers process idempotently.
- Workflow engine: configured state machines transition correctly under guards.

### 2.3 End-to-end tests
- Full journeys per persona: onboard-with-pack → configure → generate → publish → consume → substitute.
- Run **per representative segment** (see §4), not just default.
- Offline sync journeys: go offline → read → queue intent → reconnect → reconcile.

### 2.4 Contract tests
- **API contract tests** guard versioned APIs against accidental breaks (`MASTER_BACKEND §5.4`) — the backward-compatibility tripwire.
- **Event contract tests** — tolerant-reader compatibility as events evolve.
- **Integration webhook contracts** for third-party consumers.

---

## 3. Solver Testing (special rigor)

The scheduler is NP-hard, probabilistic in runtime, and safety-critical for correctness. Dedicated strategies:

### 3.1 Validity verification (the non-negotiable)
Every generated schedule is **independently verified** by a separate checker that confirms **zero hard-constraint violations** — the checker is *not* the solver (independent implementation), so a solver bug can't hide behind itself. This mirrors the DB-level double-check (`MASTER_DATABASE §6.1`): correctness is verified in depth.

### 3.2 Golden-master / reproducibility tests
Because solves are reproducible (`MASTER_SCHEDULER §9`: snapshot + engine-version + seed), we pin **golden problems → expected solutions** and detect unintended behavior drift when the engine changes.

### 3.3 Property-based testing
Generate randomized valid problems and assert **invariants** hold for any output: no double-booking, all required frequencies met, all locks respected, capacity never exceeded. Property tests find edge cases hand-written tests miss.

### 3.4 Infeasibility & explanation tests
Deliberately construct **unsatisfiable** problems and assert the engine returns a **correct Minimal Conflicting Set** (not a bare failure) — the explainability promise (`MASTER_SCHEDULER §4.5`) is tested, not assumed.

### 3.5 Linter tests
Feed known-contradictory configs and assert the linter catches them **before** a solve (arithmetic infeasibility, resource starvation, qualification gaps).

### 3.6 Performance/scale tests
Benchmark against `MASTER_PRODUCT §8` targets: small coaching (seconds), typical K-12 (seconds–minutes), university (async, partitioned). Regression-alert on solve-time degradation.

### ADR-TEST-001 — The solver is validated by an independent checker + property tests, never by trusting its own output
**Rationale.** A solver that grades its own homework is worthless for a correctness-critical product. Independent verification + invariants + golden masters give provable validity. ❌ *Trust solver output* rejected outright.

---

## 4. Configuration-Matrix Testing (the defining strategy)

The core thesis — *segments differ by data, not code* — is only credible if **proven across segments continuously**.

### 4.1 Segment fixtures
We maintain **canonical tenant fixtures**, one per major segment, each a realistic full configuration:
`CBSE-K12`, `ICSE-K12`, `TN-State`, `IB-DP`, `Indian-College-Semester`, `Coaching-JEE`, `Government-UDISE`. Each fixture has representative hierarchy, roles, calendar, subjects, resources, constraints, and vocabulary.

### 4.2 The matrix
Key journeys (onboard, generate, publish, consume, substitute, report) run **against every segment fixture** in CI. A change that passes CBSE but breaks Coaching **fails the build**. This is the mechanism that keeps one codebase honestly serving all segments.

### 4.3 New-segment onboarding test
Adding a Configuration Pack requires adding a fixture + matrix run — proving the *new* segment works **without code changes** (the thesis, enforced as a gate).

### ADR-TEST-002 — CI runs the full journey suite across a segment fixture matrix
**Rationale.** Without this, "configurable for all segments" is an untested marketing claim that silently rots. The matrix converts the product thesis into a continuously-verified fact. It is the single most important test asset. ❌ *Test only default config* rejected (would let segment-specific breakage ship).

---

## 5. Tenant-Isolation & Security Testing

Given isolation is *Critical* (`MASTER_SECURITY §4`):
- **Cross-tenant access tests:** actively attempt to read/write across tenants at every layer; assert app-scope, RLS, and key-collisions all block it.
- **Authorization tests:** deny-by-default verified; org-scoped roles verified (HOD can't reach another department); privilege-escalation attempts fail.
- **Penetration testing** (periodic, external) and **automated security scanning** in CI (dependency, secrets, SAST/DAST) (`MASTER_SECURITY §7`).
- **Privacy tests:** data-minimization in AI prompts; residency routing; erasure/retention flows.

### ADR-TEST-003 — Isolation is tested adversarially and continuously, not assumed
**Rationale.** A leak is catastrophic and cross-tenant; happy-path tests won't find it. We *attack* our own isolation in CI. ❌ *Assume RLS works* rejected.

---

## 6. Configuration & Backward-Compatibility Testing

- **Config resolution correctness:** exhaustive tests of layer precedence, locks, and provenance across the 7-layer stack.
- **Migration tests:** every schema/config-definition migration tested **forward and backward** on the multi-segment fixtures (`MASTER_DATABASE §10`) — no tenant's saved config breaks.
- **Version-pinning tests:** a schedule generated under config vN reproduces identically later (reproducibility guarantee, Principle #6).
- **Pack-update tests:** adopting a pack update is non-destructive to a diverged tenant.

---

## 7. Frontend & UX Testing

- **Component tests** for the design system, including **label-resolution** (tenant vocabulary renders correctly) and **localization/RTL**.
- **Accessibility tests** (automated + manual) against WCAG (`MASTER_FRONTEND §8`).
- **Offline tests:** service-worker behavior, local replica reads, intent-write queue/replay, reconnect reconciliation.
- **Low-end performance tests:** consumption app on constrained device/network profiles (`MASTER_FRONTEND §12`).
- **Visual regression** for key surfaces.

---

## 8. AI Testing

Per `MASTER_AI §10`:
- **NL→constraint accuracy** against a labeled utterance→mapping dataset; regression-gated on model/provider swaps.
- **Explanation faithfulness** — rendered text verified against structured engine output (no hallucinated reasons).
- **Guardrail tests** — ambiguous input triggers clarification, not a wrong guess; no-fit input is admitted, not forced.
- **Privacy tests** — no student PII leaks into prompts when disallowed.
- **Non-authority tests** — assert AI cannot mutate state without confirmation and cannot make access decisions.

---

## 9. Non-Functional Testing

| Type | What it verifies | Target source |
|---|---|---|
| **Load/stress** | 100k-tenant scale, concurrent solves, noisy-neighbor fairness | `MASTER_PRODUCT §8`, `ARCHITECTURE §3.2` |
| **Performance** | Solve times, config-cache hit rate, API latency, sync lag | NFR table |
| **Resilience/chaos** | Service failure, queue backlog, provider outage → graceful degradation | `ARCHITECTURE` |
| **Recovery** | Backup restore, per-tenant recovery, event-log replay rebuilds derived stores | `DATABASE §7,§8` |
| **Disaster** | Region failover for residency-bound tenants | `SECURITY §10` |

---

## 10. Test Environments & Data

- **Environments:** dev → staging → prod, plus isolated stacks for Silo-tier validation.
- **Test data:** synthetic, privacy-safe fixtures (never real student data in non-prod); segment fixtures (§4) are the backbone.
- **Ephemeral test tenants:** spun up per test run, torn down — proving provisioning works and keeping tests isolated.

---

## 11. Quality Gates & CI/CD Integration

A change reaches production only after (mapped to `MASTER_DEPLOYMENT`):
1. Unit + integration + contract tests pass.
2. **Segment-matrix journey suite passes (all fixtures).**
3. **Solver validity + property + infeasibility tests pass.**
4. **Isolation/security scans pass.**
5. Migration forward/backward tests pass.
6. Performance regression within budget.
7. Accessibility + offline suites pass.

### ADR-TEST-004 — The segment matrix and solver validity are blocking CI gates
**Rationale.** These two encode the product's core promises (all-segments, provable correctness). If they aren't *blocking*, the promises erode silently. Everything else is important; these are existential.

---

## 12. Testing Invariants (non-negotiable)

1. **Every generated schedule is independently verified for zero hard-constraint violations.**
2. **Key journeys run across the full segment fixture matrix in CI.**
3. **Tenant isolation is tested adversarially and continuously.**
4. **Every migration is tested forward and backward on multi-segment fixtures.**
5. **Reproducibility (version-pinned solves) is a tested guarantee.**
6. **AI is tested for faithfulness, privacy, and non-authority.**
7. **Every fixed bug adds a permanent regression test.**
8. **The segment matrix and solver validity are blocking release gates.**

---

**END OF MASTER_TESTING.md**
