# MASTER_CODING_GUIDELINES.md
### EduFlow AI — Engineering Standards & Coding Guidelines
**Document Type:** Developer Experience — Single Source of Truth
**Inherits from:** ALL prior MASTER documents
**Version:** 1.0

---

## 0. Purpose

This document defines **how engineers write code** so the architecture survives 10 years and hundreds of contributors without decaying. Architecture decays not through big bad decisions but through thousands of small ones. These guidelines are the daily discipline that keeps the modular monolith from rotting, keeps "difference is data not code" true, and keeps backward compatibility sacred.

Where a guideline encodes a `MASTER_*` invariant, it is **mandatory and CI-enforced**; where it's stylistic, it's strong convention.

---

## 1. The Prime Directives (the rules that protect the thesis)

These are the guidelines that, if violated, break the *product*, not just the code:

### 1.1 NEVER fork behavior by segment in code
There is no `if (tenant.board === 'CBSE')` anywhere, ever. Segment differences are **configuration** resolved through the Config Engine (`MASTER_BACKEND §3`). A conditional on tenant identity/segment is a **build-failing violation**.

> **Test:** if you're about to write code that behaves differently for a school type, stop — that behavior belongs in a `setting_definition`, `constraint_template`, `time_model`, or Configuration Pack.

### 1.2 NEVER read another module's tables
Modules communicate through **public interfaces only** (`MASTER_BACKEND ADR-BE-002`). Cross-module DB access is CI-enforced-failed. This is what keeps future service-extraction possible.

### 1.3 NEVER query without a tenant scope
Every data access carries Tenant Context; RLS is the backstop, not the license to be careless (`MASTER_SECURITY §4`). Un-scoped queries are forbidden and detected.

### 1.4 NEVER break backward compatibility silently
APIs are versioned and additive; schema changes are expand-migrate-contract; events are tolerant-reader. A breaking change without a version + deprecation window is forbidden (Principle #10).

### 1.5 NEVER let AI mutate state or decide access
AI produces **proposals** only (`MASTER_AI`). Code that applies AI output without human confirmation, or uses AI for authorization, is forbidden.

### 1.6 NEVER hard-code user-facing strings or abstract primitives
All user-facing text goes through localization + tenant vocabulary (`MASTER_FRONTEND §4`). No literal "Learner-Group" or hard-coded English reaches a user.

### ADR-CG-001 — The Prime Directives are mechanically enforced, not merely documented
**Rationale.** A guideline that relies on memory will be violated at scale. Each Prime Directive maps to an automated check (lint rule, fitness test, CI gate). Documentation states the *why*; automation guarantees the *what*. ❌ *Convention-only enforcement* rejected (won't survive hundreds of contributors over 10 years).

---

## 2. Language, Typing & Style

- **Strong typing everywhere** (`MASTER_BACKEND §1`) — no untyped escape hatches in domain code; types are documentation that can't go stale.
- **One core language** for the monolith; polyglot only across service boundaries (`MASTER_ARCHITECTURE ADR-008`).
- **Consistent formatting/linting**, auto-applied, non-negotiable, CI-gated — zero bikeshedding on style.
- **Explicit over clever** — code is read far more than written; optimize for the next engineer, not for brevity.
- **Immutability by default** — especially for config, events, and anything version-pinned (aligns with pure-function config resolution, `MASTER_BACKEND ADR-BE-003`).

---

## 3. Architectural Discipline in Code

### 3.1 Clean layering within modules
`API/handler → application service (use-cases) → domain → persistence` (`MASTER_BACKEND §2.1`):
- **Domain layer is framework-free and pure** — business rules unit-testable in isolation, no DB/HTTP leaking in.
- **Persistence is hidden** behind repository interfaces owned by the module.
- **Handlers are thin** — orchestrate, don't contain business logic.

### 3.2 Dependencies point inward
Domain depends on nothing external; outer layers depend on inner. Framework, DB, and transport are details at the edge — so we can swap them over a 10-year horizon without rewriting business rules.

### 3.3 Ubiquitous domain language
Use the **canonical glossary** (`MASTER_PRODUCT §11`) exactly: `Tenant`, `Org Unit`, `Learner-Group`, `Deliverable-Unit`, `Resource`, `Time-Model`, `Assignment`, `Constraint`, `Schedule`. No synonyms in code (no "class"/"section"/"batch" in the domain layer — those are tenant *labels*, resolved only at render).

### ADR-CG-002 — Domain code uses abstract canonical terms; tenant vocabulary exists only at the presentation edge
**Rationale.** If "batch" or "section" leaks into the domain/schema, we've segment-forked the model and broken the thesis. The abstract term is the model's truth; the tenant word is a label applied last (`MASTER_FRONTEND ADR-FE-003`). ❌ *Segment words in domain code* rejected.

---

## 4. Configuration-First Development (a mindset, not a feature)

Before writing any behavior, ask: **"Should this be configurable?"** For this product the default answer is *yes* for anything that could vary by institution.

- New institution-varying behavior → a `setting_definition` (+ default + which layer + lockable) — never a code branch.
- New kind of rule → a `constraint_template` + handler (`MASTER_SCHEDULER §3.2`).
- New time structure → a `time_model` compiler (`MASTER_SCHEDULER ADR-SCH-001`).
- New institution type → a Configuration Pack + fixture (`MASTER_TESTING §4.3`) — proving it works *without code change*.

This is the daily habit that keeps the thesis true.

---

## 5. Data & Migration Discipline

- **Every business table:** `tenant_id`, audit columns, soft-delete, `row_version` (`MASTER_DATABASE §2`).
- **Every unique key is `tenant_id`-leading** (`MASTER_DATABASE §5`).
- **Migrations are expand-migrate-contract**, forward-and-backward tested on segment fixtures (`MASTER_DEPLOYMENT §4`).
- **No destructive migration** without a deprecation window and a data-safety review.
- **Config-definition changes migrate existing config values** — never orphan a live tenant.
- **Outbox event on every state change** — atomic with the business write (`MASTER_BACKEND ADR-BE-005`).

---

## 6. API & Event Contracts

- **Versioned APIs**, additive evolution, contract-tested (`MASTER_TESTING §2.4`).
- **Idempotency keys** on all mutations (`MASTER_BACKEND §5.3`) — flaky networks are the norm for our users.
- **Structured, localized, explainable errors** — stable codes + translatable messages, never raw traces (`MASTER_BACKEND §11`).
- **Events are versioned and immutable; consumers are idempotent and tolerant readers.**
- **Explainability is a contract:** engine outputs (solve results, rejections) always carry structured reasons (`MASTER_SCHEDULER §4.5`).

---

## 7. Security in Code (secure by default)

- **Parameterized queries only** — no string-built SQL (`MASTER_SECURITY §7`).
- **Authorization at the central checkpoint** — never ad-hoc per-handler permission logic (`MASTER_BACKEND ADR-BE-006`).
- **No secrets in code/repos/images** — managed store only (`MASTER_SECURITY §5.2`).
- **Validate all input at boundaries; encode all output.**
- **Minimize PII in logs, prompts, and events** — especially minors' data (`MASTER_SECURITY §6`).
- **Least-privilege** for service credentials and integrations.

---

## 8. Testing Discipline (writing testable code)

- **Domain logic is pure and unit-tested** (enabled by clean layering).
- **Every bug fix ships with a regression test** (`MASTER_TESTING §1`).
- **New segment behavior ships with a fixture + matrix coverage** (`MASTER_TESTING §4`).
- **New constraint/time-model ships with validity + property tests** (`MASTER_TESTING §3`).
- **Test behavior, not implementation** — so refactoring stays cheap for a decade.
- Code that can't be tested without heavy mocking is a **design smell** — fix the design.

---

## 9. Performance-Aware Coding

- **Respect the config cache** — resolve through the engine, don't bypass; don't cause cache stampedes.
- **No N+1** — batch reads; the frontend uses aggregated GraphQL for a reason (`MASTER_ARCHITECTURE ADR-004`).
- **Async for heavy work** — the interactive path never solves, never does bulk IO synchronously (`MASTER_BACKEND §8`).
- **Index for tenant-scoped access patterns** (`tenant_id`-leading).
- **Measure before optimizing** — but design with the NFR budgets (`MASTER_PRODUCT §8`) in mind.

---

## 10. Code Review Standards

Every change is reviewed against a checklist derived from the Prime Directives:
- [ ] No segment-forking conditional (§1.1)
- [ ] No cross-module table access (§1.2)
- [ ] All queries tenant-scoped (§1.3)
- [ ] Backward-compatible / properly versioned (§1.4)
- [ ] Any AI output is proposal-only (§1.5)
- [ ] No hard-coded user strings/primitives (§1.6)
- [ ] Config-first: should this be configurable? (§4)
- [ ] Tests included (regression/matrix/validity as applicable) (§8)
- [ ] Security: parameterized, authorized centrally, no secrets, minimal PII (§7)
- [ ] Clear domain language, clean layering (§3)

### ADR-CG-003 — Review checklist is derived from architecture invariants
**Rationale.** Reviews should protect the architecture, not just catch typos. Tying the checklist to invariants makes every review a defense of the product's core promises. Reviewers are the human layer atop the automated gates.

---

## 11. Documentation & Knowledge Discipline

- **ADRs for significant decisions** — the *why* is preserved, in the style of this document set (decision → context → alternatives → rationale → consequences). A 10-year codebase whose reasoning is lost is unmaintainable.
- **Public interfaces are documented** (the module contracts other teams depend on).
- **The MASTER documents are the source of truth** — code that contradicts them is wrong; if reality demands a change, amend the MASTER doc *first*, with review.
- **Self-documenting code** preferred over comments explaining *what*; comments explain *why* where non-obvious.

### ADR-CG-004 — The MASTER documents govern; code conforms or the document is formally amended
**Rationale.** Without a single source of truth, a large team drifts into incoherence. The MASTER set is that source; divergence is resolved by conscious amendment (reviewed), never by silent code drift. This is what makes the documentation "guide development for the next 10 years" real.

---

## 12. Dependency & Supply-Chain Discipline

- **Minimize dependencies**; each is a 10-year liability.
- **Pin and scan** (`MASTER_SECURITY §7`); maintain SBOM.
- **Prefer boring, mature, well-supported** libraries over novel ones for core paths — especially the solver kernel and datastore.
- **Abstract volatile externals** behind interfaces (AI provider, `MASTER_AI ADR-AI-004`; datastore; inference) so a decade of vendor churn doesn't force rewrites.

---

## 13. Git & Delivery Workflow

- **Small, focused, reviewable changes** — large PRs hide architecture violations.
- **Trunk-based or short-lived branches**; every merge passes the full CI gate (`MASTER_DEPLOYMENT §7`).
- **Conventional, meaningful history** — commits explain intent; the log is a 10-year archaeological record.
- **Feature flags** to merge incomplete work safely (deploy ≠ release, `MASTER_DEPLOYMENT ADR-DEP-004`).

---

## 14. Coding Invariants (non-negotiable)

1. **No segment-forking conditionals** — behavior varies by config, never by `if (segment)`.
2. **No cross-module table access** — interfaces only.
3. **No un-scoped queries** — tenant context always.
4. **No silent breaking changes** — versioned, additive, deprecation windows.
5. **No AI-driven state change or access decision** — proposals only.
6. **No hard-coded user strings or abstract primitives at the UI** — localized tenant vocabulary.
7. **Domain code uses canonical terms; tenant words live only at the edge.**
8. **The MASTER documents govern; divergence is a bug or a formal amendment.**

---

**END OF MASTER_CODING_GUIDELINES.md**
