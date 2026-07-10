# MASTER_AI.md
### EduFlow AI — AI Systems Architecture
**Document Type:** AI Architecture — Single Source of Truth
**Inherits from:** MASTER_PRODUCT, MASTER_ARCHITECTURE, MASTER_SCHEDULER, MASTER_BACKEND
**Version:** 1.0

---

## 0. Purpose & Philosophy

This document defines **where AI genuinely earns its place** in the platform, and — equally important — **where it must not go**. The product is named "EduFlow **AI**," which creates a dangerous temptation to sprinkle AI everywhere. This document resists that.

**Governing philosophy:** *AI augments configuration and explanation; it never replaces the deterministic engines that guarantee correctness.* The scheduler (`MASTER_SCHEDULER`) is a **constraint solver**, not a language model — because timetable correctness must be provable, not probabilistic. AI sits *around* the deterministic core: helping users express intent, understand results, and operate faster.

Two non-negotiable principles inherited from `MASTER_PRODUCT`:
- **Explainability over magic** (Principle #7).
- **Never silent** — AI proposes; humans confirm; the system records the human decision.

---

## 1. Where AI Belongs (and Where It Does Not)

### ✅ AI is appropriate for:
1. **Natural-language → constraint translation** (help users express rules).
2. **Explanation rendering** (turn the engine's structured explanations into plain language).
3. **Conflict-resolution suggestions** (recommend which rule to relax, phrased helpfully).
4. **Substitution & optimization recommendations** (rank options with human-readable reasoning).
5. **Onboarding assistance** (guide pack selection & setup conversationally).
6. **Anomaly & insight surfacing** (flag "this teacher is overloaded," "this room is underused").
7. **Report/document drafting** (narrative summaries of a timetable or term).

### ❌ AI is explicitly NOT used for:
1. **Producing the timetable itself.** The solve is deterministic CP (`MASTER_SCHEDULER ADR-003`). An LLM must never *generate* assignments — it can't guarantee hard-constraint satisfaction, can't be reproduced, and can't be defended to a principal.
2. **Making authorization or policy decisions.** Access and governance are deterministic (`MASTER_SECURITY`).
3. **Silently mutating configuration or schedules.** Every AI action is a *proposal* requiring confirmation.
4. **Being the source of truth for any fact.** AI outputs are suggestions over the authoritative relational core.

### ADR-AI-001 — Deterministic engines own correctness; AI owns intent-capture and explanation
**Rationale.** Schedules and access control require *provable* correctness and *reproducibility* (Principles #6, #7). LLMs are probabilistic and non-reproducible. Using AI for the solve would forfeit the platform's core trust guarantees. AI's leverage is the *human-language boundary* — translating messy human intent into precise engine inputs, and precise engine outputs back into human language. ❌ *"LLM generates the timetable"* rejected as fundamentally incompatible with the product's correctness promise.

---

## 2. Capability 1 — Natural-Language → Constraint Translation

The single highest-value AI feature. It makes the powerful-but-abstract constraint vocabulary (`MASTER_SCHEDULER §3`) accessible to non-technical users.

- **Input:** a coordinator types "No teacher should teach more than 3 periods in a row" or "Science labs in the morning please."
- **AI action:** map the utterance to one or more **`constraint_template`** instances with typed parameters and scope (`MASTER_DATABASE §2.6`).
- **Output:** a **structured proposal** shown in the UI: "I'll add a *max-consecutive-teaching* hard constraint = 3, applied to all teachers. Confirm?" — with an editable form.
- **Human confirms** → the constraint is created (as data), tagged `source = nl-assisted`, storing the original `natural_language_text` for explainability.

### ADR-AI-002 — NL translation targets the *existing* constraint vocabulary; it never invents new constraint semantics
**Rationale.** AI maps language to a **closed, validated vocabulary** of templates the engine understands — it does not synthesize arbitrary logic. This keeps every constraint solvable, lintable, and explainable, and prevents the AI from creating rules the engine can't reason about. ❌ *AI emits free-form constraint code* rejected (unsolvable/unsafe outputs, breaks the linter and explainer).

**Guardrails:**
- If the utterance is ambiguous, the AI **asks a clarifying question** rather than guessing.
- If no template fits, it says so plainly ("I can't express that yet") rather than forcing a wrong mapping.
- The proposal always runs through the **constraint linter** (`MASTER_SCHEDULER §4.3`) before the user commits, catching contradictions early.

---

## 3. Capability 2 — Explanation Rendering

The engine already produces **structured explanations** (`MASTER_SCHEDULER §4.5`): minimal conflicting sets, unmet-preference lists, per-assignment reason chains. The AI's job is to **render these into clear, localized, audience-appropriate prose** — never to invent the reasoning.

- **Failure:** engine returns "hard constraints {A, B, C} are mutually unsatisfiable" → AI renders: "These three rules can't all be true at once: you've pinned Physics to period 1, but also required no Science before period 3, and Class 10 needs Physics daily. Relaxing any one will let generation succeed."
- **Trade-off:** engine returns unmet soft goals with costs → AI renders a prioritized, plain summary.
- **Per-assignment:** "Why is Physics here?" → AI narrates the engine's reason chain.

### ADR-AI-003 — AI renders explanations; the engine owns their truth
**Rationale.** The *content* of an explanation must be exactly what the deterministic engine computed (auditable, reproducible). The AI only improves *readability and localization*. It must never add reasons the engine didn't produce (hallucination = broken trust). A verification step ensures the rendered explanation is faithful to the structured input.

---

## 4. Capability 3 — Substitution & Optimization Recommendations

Builds on the deterministic substitution engine (`MASTER_SCHEDULER §6`), which produces **valid, ranked** options. AI adds a **reasoning layer** on top:

- The engine guarantees the options are *valid* (qualified, free, policy-compliant).
- The AI **explains and contextualizes** the ranking ("Ms. Rao is the best fit: qualified, free, and this keeps her under her daily cap; Mr. Sen is possible but would give him a 4th consecutive period").
- The human picks; the AI never auto-applies.

The *validity* is deterministic; the *narrative* is AI. This separation keeps recommendations trustworthy.

---

## 5. Capability 4 — Onboarding Assistant

A conversational guide for setup (`MASTER_PRODUCT §7.1`):
- Recommends a **Configuration Pack** from a short description ("We're a CBSE school, 40 sections, 6-day week") → suggests `CBSE-K12`.
- Walks the admin through hierarchy, calendar, subjects — **filling the setup wizard's forms as proposals** the admin confirms.
- Lowers time-to-first-timetable (a key Success Metric).

Every action remains a **confirmable proposal** populating deterministic configuration — the assistant is a faster path to the same config screens, never a bypass of them.

---

## 6. Capability 5 — Insights & Anomaly Detection

Analytical (often non-LLM) intelligence over the warehouse (`MASTER_DATABASE §8`):
- Teacher workload imbalance, room under/over-utilization, subject-spread issues, chronic substitution hotspots.
- Surfaced as **advisory insights** with drill-down, never auto-acted.
- Uses statistical/analytical methods primarily; LLM only to phrase the finding.

---

## 7. Capability 6 — Report & Document Drafting

AI drafts **narrative summaries** (a term-in-review, a timetable overview for a newsletter) from authoritative data. Drafts are **editable proposals**; the underlying numbers come from the deterministic core, not the model. Copyright/policy-safe generation only.

---

## 8. AI System Architecture

The **AI Service** is an extracted workload (`MASTER_ARCHITECTURE §2`), isolated for cost, rate-limiting, and its external-inference dependency.

```
User intent ─> Core ─> AI Service ─┬─> (LLM inference: external or hosted)
                                    ├─> Template/vocabulary catalog (grounding)
                                    ├─> Tenant config context (grounding)
                                    └─> Structured proposal ─> Core ─> Human confirm
```

### 8.1 Grounding & Retrieval
- AI operations are **grounded** in authoritative context: the tenant's constraint vocabulary, existing config, and vocabulary labels — retrieved and supplied to the model, so outputs map to *this tenant's* real entities and words.
- This retrieval-grounded approach **reduces hallucination** and keeps proposals actionable.

### 8.2 Provider abstraction
### ADR-AI-004 — Abstract the inference provider behind an interface
**Rationale.** Models and providers change yearly; a 10-year platform cannot hard-bind to one. An **AI-provider abstraction** lets us swap/host models, route by cost/capability, and keep sensitive tenants on stricter (e.g., zero-retention or self-hosted) inference. ❌ *Direct provider SDK calls throughout* rejected (lock-in, no per-tenant routing, compliance risk).

### 8.3 Cost & rate governance
- AI calls are **metered per tenant**, rate-limited, and cached where deterministic (identical NL rule → cached mapping).
- Heavy/optional AI is a **feature-flagged capability** (some tenants disable it entirely — govt data policies).

---

## 9. Safety, Privacy & Governance

Given a core segment is **children's data** in schools, AI governance is strict:

1. **Data minimization:** AI receives only the context needed for the task; student PII is excluded from prompts unless strictly necessary and permitted.
2. **Tenant control:** AI features are **opt-in per tenant**; a government tenant can disable all external inference (routing to self-hosted or off).
3. **No training on tenant data** without explicit contractual consent; default is **no retention** at the provider.
4. **Human-in-the-loop always:** no AI output changes state without confirmation (Principle: never silent).
5. **Faithfulness checks:** explanation-rendering is validated against the engine's structured output to prevent hallucinated reasons.
6. **Auditability:** every AI-assisted action records the prompt-intent, the proposal, and the human decision as domain events (`MASTER_DATABASE §7`).
7. **Bias & fairness review:** recommendation features (substitution, workload) are reviewed to avoid systematically disadvantaging staff; the deterministic engine's fairness constraints (workload balance) do the real work, AI only narrates.

### ADR-AI-005 — AI is opt-in, data-minimized, non-authoritative, and fully audited
**Rationale.** Trust with schools and governments is existential. An AI feature that leaked student data or silently changed a timetable would be catastrophic. Constraining AI to *proposals over minimal data with full audit* makes it safe to offer even to the most cautious tenant. ❌ *Always-on, data-rich AI* rejected on privacy/compliance grounds.

---

## 10. AI Evaluation & Quality

- **NL-translation accuracy** measured against a labeled test set of utterances → expected constraint mappings (`MASTER_TESTING`).
- **Explanation faithfulness** measured: does the rendered text match the structured input? (Automated checks + human review.)
- **Recommendation acceptance rate** tracked (do users pick AI's top suggestion?).
- **Regression guardrails:** provider/model swaps run the eval suite before rollout — AI behavior is versioned and tested like any other component (10-year discipline).

---

## 11. AI Invariants (non-negotiable)

1. **AI never generates the timetable** — the deterministic solver does.
2. **AI never mutates state silently** — every action is a confirmable proposal.
3. **AI maps only to the existing constraint vocabulary** — it invents no engine semantics.
4. **AI renders explanations but never fabricates reasons** — faithful to engine output.
5. **AI is opt-in per tenant, data-minimized, and fully audited.**
6. **The inference provider is abstracted** — swappable, per-tenant-routable.
7. **AI never makes authorization or policy decisions.**
8. **AI outputs are grounded in authoritative tenant context** to prevent hallucination.

---

**END OF MASTER_AI.md**
