# EduFlow AI — First-Time Tester Guide

**Who this is for:** someone who has never seen this system and needs to verify it actually works, end to end.

**The single most important thing to understand:** EduFlow is a *dependency chain*. The timetable
generator is a constraint solver — it can only run once every input it depends on exists and is
internally consistent. Roughly 90% of "the generator is broken" reports are actually
"the data wasn't set up in the right order."

**So: follow the order in [Part 3](#part-3--setup-order-do-not-skip-or-reorder). Do not skip steps.**

Everything below has been executed against a live server and a real PostgreSQL database.

---

## Part 1 — Prerequisites

| Requirement | Check it |
|---|---|
| PostgreSQL running | `psql -U postgres -h localhost -c "SELECT 1"` |
| Database + role exist | `psql -U eduflow -h localhost -d eduflow_ai -c "\dt"` → should list 24 tables |
| Python deps installed | `backend/venv/Scripts/python.exe -c "import fastapi, ortools; print('ok')"` |
| `backend/.env` configured | `DATABASE_URL` points at Postgres, `SECRET_KEY` is set |

If the database is empty, create the schema and the first admin:

```bash
cd backend
venv/Scripts/python.exe seed_admin.py     # creates 24 tables + admin@eduflow.com / Admin@123
```

> ⚠️ `Admin@123` is a default committed in source. Change it before any real deployment.

---

## Part 2 — Start the system

```bash
cd backend
venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8010
```

The backend serves **both** the API and the admin console from one origin (so there is no CORS to configure):

| What | URL |
|---|---|
| **Admin console (start here)** | <http://127.0.0.1:8010/app/> |
| API docs (Swagger) | <http://127.0.0.1:8010/docs> |
| Health check | <http://127.0.0.1:8010/health> |

**Login:** `admin@eduflow.com` / `Admin@123`

**Smoke test before going further.** If any of these fail, stop and fix the environment:

```bash
curl http://127.0.0.1:8010/health                      # -> {"status":"ok"}
curl -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8010/app/index.html   # -> 200
```

---

## Part 3 — Setup order (do not skip or reorder)

Each step depends on the ones above it. The **Why it matters** column tells you what breaks if you skip it.

| # | Step | Where | Why it matters |
|---|---|---|---|
| 1 | **School** | Schools | Defines `periods_per_day` × `working_days` = the slot grid. Everything is scoped to a school. |
| 2 | **Configuration** | Config Editor | Chooses assignment mode, resources on/off, scheduling policies. The scheduler reads this, not hardcoded rules. |
| 3 | **Classes** | Classes | A class is a grade ("Grade 5"). |
| 4 | **Sections** | Classes → Sections | A section ("5A") is what actually receives a timetable. **No sections ⇒ nothing to schedule.** |
| 5 | **Resources** *(optional)* | Resources | Labs/rooms. Two subjects needing the same lab can never share a slot. |
| 6 | **Subjects** | Subjects | Each carries `weekly_hours` — the demand the solver must satisfy **exactly**. |
| 7 | **Teachers** | Teachers | **Must be linked to the subjects they can teach.** A subject with no qualified teacher makes generation impossible. |
| 8 | **Availability** *(optional)* | Teacher Availability | Blocks specific day/period cells for a teacher. |
| 9 | **Assignments** | Assignments | **Required if** `teacher_assignment_method` is `manual` or `hybrid`. Binds *section × subject → teacher*. |
| 10 | **Validate** | `GET /validation/school/{id}` | Tells you whether you're ready *before* you waste a solve. |
| 11 | **Generate** | Timetable → Generate | Runs OR-Tools CP-SAT. |

### The two arithmetic rules that decide whether a solve is even possible

Get these wrong and no amount of retrying will help.

**Rule 1 — Section capacity.** A section cannot be taught more periods than it has slots:

```
sum(weekly_hours of all subjects) + sum(activity hours)  ≤  periods_per_day × working_days
```
> Example: 6 periods/day × 5 days = 30 slots. Subjects totalling 23 hours ✅. Totalling 34 ❌.

**Rule 2 — Subject spread.** By default a subject may appear **at most once per day per section**:

```
weekly_hours of any subject  ≤  working_days          (default)
weekly_hours of any subject  ≤  working_days × 2      (if double_periods_allowed = true)
```
> Example: Math 6 hrs/week on a 5-day week is **impossible** by default — 6 > 5.
> Either drop Math to 5 hours, or set `"scheduling_policies": {"double_periods_allowed": true}` in the config.
>
> This is the single most common cause of a failed generate. The system now tells you so explicitly.

**Rule 3 — Teacher capacity.** For each teacher:

```
sum(weekly_hours of their subjects × number of sections they teach)  ≤  max_weekly_hours
```

---

## Part 4 — Generate and verify the timetable

Click **Generate** on the Timetable page (or `POST /timetables/generate`).

A successful generate writes rows straight into the **live** timetable table. It **deletes all unlocked
rows** for that school and replaces them; **locked rows are preserved**. Row IDs change on every
generate — don't cache them.

### What a *correct* timetable must satisfy

These are hard guarantees. If any is violated, that's a bug — report it.

- [ ] Total rows = `sum(subject weekly_hours) × number of sections`
- [ ] No section has two lessons in the same (day, period)
- [ ] **No teacher is in two places at once** across all sections
- [ ] No resource (lab/room) is double-booked
- [ ] Each (section, subject) appears **exactly** its `weekly_hours` times
- [ ] No teacher exceeds `max_weekly_hours`
- [ ] No lesson lands on a slot the teacher marked unavailable
- [ ] Lab-bound subjects carry their `resource_id`

Spot-check in the UI via the **section grid** and the **teacher grid** — a teacher grid with two
subjects in one cell is an immediate red flag.

### Locking

Lock a slot (pin it), then regenerate. The locked slot **must** survive unchanged. This is how
admins hand-place a lesson the solver isn't allowed to move.

---

## Part 5 — Publish (version workflow)

Generation alone does **not** publish. Promote a timetable through:

```
save-draft  →  submit-review  →  approve  →  publish
```

Publishing rewrites the master rows from the version snapshot (so row IDs change again).
`rollback` and `compare` exist for auditing.

---

## Part 6 — Daily operations (the overlay model)

**Core invariant: the published master timetable is immutable.** Day-to-day disruptions are recorded
as *date-scoped overlays*, never by editing or regenerating the master.

**Leave → substitution:**
1. Create a leave for a teacher on a date.
2. **Approve it.** Approval automatically runs the substitute engine and creates `Substitution` rows
   for every master slot that teacher would have taught — it returns `substitutions_created` and any
   `uncovered_slots` it could not fill.
3. `GET /leaves/{id}/gaps` re-derives only the slots **still uncovered**.
   👉 **Zero gaps is the success case**, not an error — it means every slot was auto-covered.
4. `GET /substitutions/schedule?date=...` returns the *effective* schedule for that day, with
   substitutes flagged.

**Verify the invariant:** after approving a leave, the master timetable rows must be **byte-for-byte
unchanged** (same IDs, same count). Only overlay rows appear.

**Swaps:** propose a swap of two slots, then approve. If approval would double-book a teacher, the
system returns **409 Conflict** and refuses. **A 409 here is correct behaviour**, not a failure.

---

## Part 7 — Reports

Every report must reconcile with the timetable you just generated:

- `GET /reports/teacher-workload` → `sum(scheduled_periods)` **must equal** the total timetable rows.
- Also available: `subject-coverage`, `resource-usage`, `leave-summary`, `timetable`.
- Exports: `/reports/export/{name}?format=pdf|xlsx` must return a real binary (>500 bytes), not JSON.

---

## Part 8 — AI guardrail (must-not)

Groq **explains, narrates, and suggests. It never generates a timetable.**
All scheduling comes from OR-Tools CP-SAT. If a Groq outage changes your timetable, something is
badly wrong. With no `GROQ_API_KEY` set, assistant endpoints return **502** and the rest of the system
keeps working — that is expected.

---

## Part 9 — Run the automated suite

Rather than clicking through all of the above, run the full integration test. It creates its own
throwaway school and exercises every module, asserting the solver invariants.

```bash
# terminal 1
cd backend && venv/Scripts/python.exe -m uvicorn app.main:app --port 8010

# terminal 2
cd backend && venv/Scripts/python.exe test_full_integration.py
```

Expected final line:

```
TOTAL: 107 passed, 0 failed, 107 checks
```

**The suite does not fully clean up after itself**, and this is a real limitation rather than an
oversight: once a school has a generated timetable it can no longer be deleted through the API,
because no endpoint deletes timetable rows and the foreign-key guard correctly returns 409. Purge
accumulated test schools with:

```bash
cd backend && psql -U eduflow -h localhost -d eduflow_ai -v ON_ERROR_STOP=1 -f cleanup_test_data.sql
```

That script only removes schools named `IntegrationSchool-%` and never touches real data.

It covers: auth · config engine · academic data · teachers/qualifications · assignments · validation ·
**scheduler correctness invariants** · constraint linter · lock-preservation · version workflow ·
leave→substitution overlay · swaps · calendar/exams · reports + binary exports · bulk · notifications ·
**RBAC & tenant isolation** · AI guardrail · static frontend delivery.

---

## Part 10 — Troubleshooting

Actual error messages and what they really mean:

| Message | Real cause | Fix |
|---|---|---|
| `Subject 'X' needs N weekly periods … subject-spread policy allows at most 1 lesson(s) per day` | **Rule 2** violated: `weekly_hours > working_days` | Reduce the subject's hours, enable `double_periods_allowed`, or add a teaching day |
| `Required weekly periods (N) … exceed the M available slots` | **Rule 1** violated | Reduce subject hours or increase `periods_per_day` |
| `No teacher is assigned/eligible to teach subject 'X' in section 'Y'` | Teacher not linked to that subject, or (manual mode) no assignment row | Add the subject to a teacher's `subject_ids`, or create the assignment |
| `No feasible timetable exists …` | A genuine constraint clash the linter can't pre-detect (e.g. teacher caps + availability) | Raise `max_weekly_hours`, add a teacher, or unblock availability |
| `Cannot delete this school: other records still reference it` (**409**) | The school still has classes/teachers | Delete children first — this is a guard, not a bug |
| `Cannot approve: slot A's …` (**409**) | The swap would double-book someone | Correct behaviour. Pick different slots |
| Assistant endpoints return **502** | `GROQ_API_KEY` not set | Optional. Everything else works without it |
| `422` on generate | Any of the above solver errors | Read the `detail` field — it names the offending subject/section |

### Readiness scoring

`GET /validation/school/{id}` returns `readiness_score` (0–100):

- `ready_to_generate` — score ≥ **50**
- `ready_to_publish` — score ≥ **80**

---

## Part 11 — Known gotchas (current implementation)

Things that will surprise you. These are accurate as of this guide:

1. **School config is stored as a JSON *string***, not an object.
   `GET /schools/{id}/config` → `{"school_id": 1, "config": "{...}"}`
   `PUT` expects `{"config": "<json string>"}`. Sending a raw object silently ignores your changes.
2. **Only two config templates exist**: `Government` and `Private`
   (`POST /schools/{id}/apply-template` with `{"template_name": "Private"}`).
   The setup wizard's frontend advertises six presets it builds client-side — they are not backend templates.
3. **`GET /timetables` has no `school_id` filter** and `limit` is capped at **200**.
   A super_admin sees rows from *all* schools mixed together. Filter by `section_id` or `teacher_id` instead.
4. **Generate bypasses the version workflow** — it writes to the live table immediately.
   Use `save-draft` afterwards if you want an auditable version.
5. **Row IDs are not stable.** Every generate and every publish reassigns them.
6. **No Alembic migrations.** Schema is created by `Base.metadata.create_all`, so model changes do
   **not** propagate to an existing database automatically.
7. **The setup wizard performs multi-step writes from the browser** and is not atomic — a failure
   partway through can leave orphaned classes/sections.
8. **Frontend is not yet responsive.** `css/style.css` contains zero `@media` queries, so mobile and
   tablet layouts are currently broken. Test on desktop.
9. **A school with a generated timetable can never be deleted through the API.** There is no endpoint
   to delete timetable rows, so the foreign-key guard returns 409 permanently. Clean up in SQL
   (`backend/cleanup_test_data.sql`).

---

## Quick reference — a known-good minimal school

This exact configuration is verified to solve in well under a second:

```
School:    periods_per_day = 6, working_days = 5     -> 30 slots/section
Config:    teacher_assignment_method = "manual"
           subject_configuration.hours_defined_at = "per_class"
           resources.enabled = true
Classes:   Grade 5
Sections:  A, B
Resource:  Physics Lab
Subjects:  Math 5h, English 5h, Science 5h (-> Physics Lab), History 4h, Art 4h   = 23h  (≤ 30 ✅)
Teachers:  one per subject, max_weekly_hours = 20, each linked to its subject
           (each teaches 2 sections -> max load 10h ≤ 20 ✅)
Assignments: every (section × subject) -> its teacher   (10 rows)

Expected result: 46 rows (23 × 2 sections), zero conflicts.
```
