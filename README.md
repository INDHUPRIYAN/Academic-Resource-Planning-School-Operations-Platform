# EduFlow AI — Foundation

Phase 1: auth (JWT, role-based) + full normalized DB schema + project skeleton.

## Backend setup

```bash
cd backend
pip install -r requirements.txt
cp .env.example .env   # edit DATABASE_URL to your Postgres instance, set SECRET_KEY
```

Create the Postgres database first:
```sql
CREATE DATABASE eduflow_ai;
CREATE USER eduflow WITH PASSWORD 'eduflow';
GRANT ALL PRIVILEGES ON DATABASE eduflow_ai TO eduflow;
```

Bootstrap the first Super Admin (also creates all tables):
```bash
python create_superadmin.py
```

Run the API:
```bash
uvicorn app.main:app --reload --port 8000
```

Tables created (matches spec, minus dummy data): schools, users, teachers,
teacher_subjects (join table), classes, sections, subjects, activities,
resources, timetables, leaves, substitutions, swaps, exams, notifications,
audit_logs.

## Frontend

Open `frontend/index.html` in a browser (or serve via any static server) with
the backend running on `localhost:8000`. Log in with the Super Admin you just
created — it will redirect to `dashboard.html`, calling `/auth/me` to verify
the token.

## Endpoints so far

- `POST /auth/login` — returns JWT + role
- `POST /auth/logout` — confirms session, client discards token
- `GET  /auth/me` — current user, requires Bearer token
- Full CRUD (list w/ pagination+search, get, create, update, delete) for:
  `/schools`, `/classes`, `/sections`, `/subjects`, `/activities`, `/resources`, `/teachers`
- `GET /health`

Also see "OR-Tools Master Timetable Generator", "Timetable Viewer UI",
"Leave Management + Auto Substitution", "Swap Management", "Exam Module",
and "Reports" sections below for `/timetables`, `/leaves`,
`/substitutions`, `/notifications`, `/swaps`, `/exams`, and `/reports`.

All CRUD routes require a Bearer token. Writes are restricted to
`super_admin`/`school_admin` via `require_roles(...)`; `school_admin` and
`teacher` accounts are automatically scoped to their own school's data.
`/teachers` also creates the linked login (User) account and manages
subject assignments.

Reused across modules: `app/crud_factory.py` (generic list/get/create/update/
delete + audit logging) and `frontend/js/crud-page.js` (generic
table + modal + search + pagination UI).

## Frontend pages

`index.html` (login) → `dashboard.html` → `schools.html`, `classes.html`,
`subjects.html`, `teachers.html`, each fully wired to the live API (create,
edit, delete, search, pagination — no dummy data). Plus `timetable.html`
(Phase 3), `leaves.html` / `substitutes.html` (Phase 4), `swaps.html`
(Phase 5), `exams.html` (Phase 6), and `reports.html` (Phase 7).

## OR-Tools Master Timetable Generator (Phase 2)

Core scheduling feature, built with Google OR-Tools CP-SAT
(`app/services/timetable_generator.py`). AI (Groq) is never used for
scheduling — this is pure constraint programming.

**Scope note on the data model:** subjects/activities are school-wide
(there's no per-section subject list in the schema), so every section of a
school is scheduled with all of that school's subjects/activities at their
configured `weekly_hours`. `Subject`/`Activity` gained an optional
`resource_id` (e.g. point a "Chemistry" subject at a "Lab" resource) so the
solver can prevent two sections needing the same room at the same time.
`School` gained `periods_per_day` / `working_days` to size the weekly grid.
`Timetable` rows now allow either a subject lesson (`subject_id` +
`teacher_id`) or an activity (`activity_id`), since the original schema had
no way to represent an activity slot.

Endpoints (`app/routers/timetables.py`):
- `POST /timetables/generate` `{school_id, time_limit_seconds}` — runs the
  solver and replaces all **unlocked** rows for the school. `school_admin`
  is auto-scoped to their own school; `super_admin` must pass `school_id`.
  Returns 422 with a plain-English reason on infeasible input (e.g. a
  subject with no teacher assigned, or weekly hours exceeding available
  periods).
- `GET /timetables` — paginated list, filterable by `section_id`,
  `teacher_id`, `day_of_week`.
- `GET /timetables/section/{id}` — full week grid for one section.
- `GET /timetables/teacher/{id}` — full week grid for one teacher.
- `PATCH /timetables/{id}/lock?locked=true|false` — lock a slot so
  regeneration leaves it untouched (Layer 1 admin edits, per spec).
- `PUT /timetables/{id}` — manual override of a single slot (day/period/
  teacher/resource), with 409 conflict checks against section/teacher/
  resource double-booking.

Constraints enforced by the solver: no section/teacher/resource
double-booking, exact weekly hours per subject/activity per section,
teacher subject-qualification (only assigns teachers who teach that
subject), teacher `max_weekly_hours` cap, and locked-slot preservation
across regenerations (including reducing the remaining hour targets and
blocking the teacher/resource at that slot).

Verified end-to-end against a local SQLite instance (see testing note
above — same approach as Phase 1): created a school with 2 sections, 3
subjects (one requiring a shared Lab resource) + 1 activity, 3 teachers;
confirmed generation produces the exact weekly-hour counts per section, no
double-booking of sections/teachers/the shared resource, that a subject
with no teacher correctly returns 422, that a locked slot survives
regeneration, and that a manual move into an occupied slot returns 409.
`ortools` and `email-validator` (a pre-existing gap — `EmailStr` needs it)
were added to `requirements.txt`.

## Timetable Viewer / Generator UI (Phase 3)

Frontend for the Phase 2 backend — no schema or API changes this phase,
pure UI (`frontend/timetable.html`, `frontend/js/timetable.js`, plus
grid-specific styles appended to `css/style.css`). Added a "Timetable" link
to the shared top nav (`js/nav.js`).

Not a CRUD table, so it doesn't reuse `crud-page.js` — it's a days × periods
grid component with its own state machine, following the same
vanilla-JS/`apiRequest` conventions as the rest of the frontend.

What it does:
- **View by Section or Teacher** — a mode toggle switches between
  `GET /timetables/section/{id}` (pick Class → Section) and
  `GET /timetables/teacher/{id}` (pick Teacher). Grid dimensions come from
  the school's `periods_per_day`/`working_days`. Each cell shows the
  subject/activity name plus the teacher (section view) or section
  (teacher view) and resource, color-coded by kind, with a 🔒 badge on
  locked slots. Empty periods render as "Free" (no underlying row, so
  nothing to click).
- **Generate** (`super_admin`/`school_admin` only) — button + time-limit
  input calling `POST /timetables/generate`; shows a spinner while the
  solver runs, then either a success banner with the slot/section counts
  or the plain-English 422 error inline (e.g. "no teacher assigned to
  Orphan Subject").
- **Lock/unlock** — toggle button in the edit modal, calls
  `PATCH /timetables/{id}/lock`.
- **Manual edit** — clicking a populated cell (admins only) opens a modal
  to change subject/activity, teacher, resource, day, or period, calling
  `PUT /timetables/{id}`; a 409 (double-booking) is shown inline in the
  modal instead of closing it.
- **School selector** — only shown to `super_admin` when more than one
  school exists; `school_admin`/`teacher` are locked to their own school
  (matches backend scoping).

**Scope note (documented honestly, same spirit as Phase 2):** the list
endpoints for classes/sections/teachers/subjects/activities/resources don't
support a `school_id` query filter for `super_admin` (only `school_admin`
gets auto-scoped server-side), so for a `super_admin` picking a school the
page fetches up to 100 of each and filters client-side by `school_id`.
Fine at current scale; if a deployment grows past ~100 classes/teachers per
list, those endpoints should grow a proper `school_id` filter param.

Verified end-to-end against a local SQLite instance with a Python test
script (`test_timetable_ui.py`, same approach as Phases 1–2) hitting the
exact endpoints/payload shapes the frontend calls: create school → class →
2 sections → resource → 3 subjects (one resource-linked) → activity → 3
teachers → generate → fetch section grid → fetch teacher grid → lock a
slot → regenerate and confirm the locked slot survived unchanged → manual
PUT move into a free cell → PUT into an occupied cell confirms 409 →
orphan-subject school confirms 422 with a plain-English reason. All passed.

## Leave Management + Auto Substitution (Phase 4)

Endpoints: `app/routers/leaves.py`, `app/routers/substitutions.py`,
`app/routers/notifications.py`. Matching engine: `app/substitution_engine.py`
(pure decision logic, reads the DB but never writes to it — the router turns
its `SubstituteMatch` results into `Substitution` rows).

**Schema (additive):** `Leave` gained `school_id`, `end_date` (multi-day
leave), `decision_note`, `reviewed_by`, `reviewed_at`. `Substitution` gained
`method` (`same_subject` | `available` | `department_fallback` |
`workload_fallback` | `manual`), `reason` (plain-English, shown in the UI),
and `assigned_by` (null for the auto engine, a user id for manual
assignment). All nullable/defaulted, so existing rows are unaffected.

**Flow:**
1. `POST /leaves` — a teacher applies for themselves (multi-day via
   `end_date`), or an admin submits on a teacher's behalf. Starts `pending`.
2. `GET /leaves?status=&teacher_id=` — teachers see only their own; admins
   see their school's (or all, for `super_admin`).
3. `POST /leaves/{id}/reject` — admin only, records a decision note,
   notifies the teacher.
4. `POST /leaves/{id}/approve` — admin only. Marks the leave approved, then
   for every date in the leave's range, finds every master-timetable slot
   the teacher would have taught that weekday and runs
   `substitution_engine.find_substitute` per slot, in priority order:
   same-subject-and-free → any-free-teacher (lowest workload) →
   same-department fallback (double-booking possible, flagged) →
   lowest-workload-anyone fallback (flagged) → `uncovered` if literally no
   other active teacher exists at the school. Writes one `Substitution` row
   per covered slot, notifies each assigned substitute (batched into one
   notification per teacher if they picked up several slots), notifies the
   applicant of the decision, and returns the uncovered list so the admin
   UI can immediately hand them out manually.
5. `GET /leaves/{id}/gaps` — re-derives the still-uncovered slots for an
   approved leave at any later time (doesn't rely on the one-shot approve
   response — covers the case where a manual assignment is later deleted).
6. `POST /substitutions` — manual assignment (typically for a gap); `PUT
   /substitutions/{id}` reassigns; `DELETE /substitutions/{id}` removes.
   `GET /substitutions?date=&leave_id=&teacher_id=` lists for management UI.
7. `GET /substitutions/schedule?date=&section_id=&teacher_id=` — the
   **Layer 2 effective schedule**: the master timetable for that date's
   weekday with any approved substitutions for that exact date overlaid on
   read. The master `Timetable` rows are never modified by any of this —
   verified in testing that a teacher's master grid is byte-for-byte
   unchanged after their leave is approved and substituted.

**Notifications:** in-app only (`Notification` model), delivered via
`GET /notifications` (paginated, includes `unread_count`),
`PATCH /notifications/{id}/read`, `PATCH /notifications/read-all`. Written
directly by the leaves/substitutions routers at each decision point (leave
approved/rejected, substitute assigned) — no separate delivery mechanism
needed since it's in-app-list only per spec.

**Frontend:** `frontend/leaves.html` + `js/leaves.js` (teacher: apply +
cancel-own-pending + see status history; admin: pending/approved/rejected/all
tabs, approve/reject, inline gap-filling UI right in the approval result
with a teacher picker per uncovered slot). `frontend/substitutes.html` +
`js/substitutes.js` (date/section/teacher-filtered Layer-2 schedule view,
plus a management table to reassign or remove existing substitutions). Nav
bar (`js/nav.js`) gained "Leaves"/"Substitutes" links and a notification
bell with an unread-count dot and a dropdown panel (polls every 30s).

**Scope note (documented honestly, same spirit as Phases 2-3):** Swap
Management shares the `Swap` model with this phase but has no approval
workflow yet (listed separately in spec order, next up). The `_is_free`
check in the engine does not itself check `Leave.status`, since a candidate
who is also on leave that day is already filtered out one step earlier
(`_is_on_approved_leave`); this is intentional, not an oversight, but worth
knowing if you extend `_is_free` for another purpose. Department fallback
requires `Teacher.department` to be set and shared with a candidate — with
no department set anywhere, the engine falls straight to the lowest-workload
fallback tier, which is correct per spec but worth setting departments in
seed data to see tier 3 specifically fire.

Verified end-to-end against a local SQLite instance with
`test_leaves_ui.py` (same approach as Phases 1-3): apply → teacher can't
self-approve (403) → admin approves → auto-engine assigns the correct
same-subject/lowest-workload teacher for every slot → substitute and
applicant both get notifications → Layer 2 schedule shows the substitute
without touching Layer 1 → re-approving an already-decided leave is
rejected (400) → forcing every other teacher onto leave the same day
produces guaranteed `uncovered` slots → manual assignment fills a gap,
duplicate manual assignment on the same slot/date is rejected (409),
reassignment and deletion both work → reject flow and self-cancel flow both
work. All passed.

## Swap Management (Phase 5)

Lets a teacher (or admin, on a teacher's behalf) request that two
master-timetable slots exchange their effective content — subject,
teacher, activity, resource — for **one specific date**. Same Layer 2
overlay pattern as Substitution (Phase 4): the master `Timetable` rows
(`timetable_id_a` / `timetable_id_b`) are never modified. The existing
`GET /substitutions/schedule` endpoint now overlays both approved
Substitutions *and* approved Swaps for the requested date, so the
Substitutes page's day view is also the way to visually confirm a swap
landed correctly (no new "effective schedule" endpoint needed).

- Backend: `app/routers/swaps.py` (new router, purpose-built rather than
  `crud_factory` since it's an approval state machine like Leave, not
  plain CRUD).
- Schema additions (additive, on the pre-existing `Swap` model): `status`
  (pending/approved/rejected), `requested_by`, `reason`, `decision_note`,
  `reviewed_by`, `reviewed_at`, `school_id`. The original
  `timetable_id_a`/`timetable_id_b`/`date`/`approved_by` fields are used
  as originally specified.
- `EffectiveSlotOut` gained `is_swapped` and `swap_partner_label` (additive,
  default `False`/`None`), alongside the existing `is_substituted`.
- **Constraint**: both slots must share the same `day_of_week`, and that
  `day_of_week` must equal the request `date`'s weekday. A swap is a
  same-day exchange of two periods/classes (either the same section
  reordering its own day, or two different sections/teachers trading
  same-day classes) — not a move to a different day. Enforced at request
  time (400 if violated).
- **Permission**: a teacher may request a swap only if they teach one of
  the two slots; an admin may request any swap within their school. Either
  the requester or an admin can cancel a still-pending request.
- **Approval validation**: on approve, each side is re-checked so neither
  teacher (nor resource, if set) ends up double-booked at the position
  they're moving into — checked against the master timetable, any existing
  approved Substitution, and any other approved Swap for that date. A
  conflict on either side blocks the whole approval with 409; there is no
  fallback tier (unlike Substitution) since a swap is a voluntary schedule
  change, not a mandatory coverage requirement — the admin resolves it
  manually (reject, or ask the teachers to pick different slots).
- **Notifications**: both affected teachers (if their slot's teacher isn't
  the approving admin, and skipping a duplicate if the same teacher owns
  both slots) plus the requester (if they weren't already notified as one
  of the teachers) get an in-app notification on approval; the requester
  gets one on rejection too.
- Documented scope note: if a slot is targeted by both an approved
  Substitution and an approved Swap on the same date (rare — e.g. a
  teacher who was about to swap goes on approved leave before the swap
  date arrives), the Substitution overlay wins for that slot when
  computing the effective schedule; the swap's other side still displays
  normally. This is the Phase-5 analogue of Phase 4's documented
  department-fallback note: an edge case worth knowing about, not a bug.
- Frontend: `frontend/swaps.html` + `js/swaps.js` — a request form (date
  picker computes the weekday and loads that day's slots via
  `GET /timetables?day_of_week=&limit=`; teachers only see their own slots
  in the first picker, admins see everything in both) plus a
  pending/approved/rejected/all list with approve/reject (admin) and
  cancel (requester/admin) actions. `frontend/js/substitutes.js` gained a
  "Swapped" row style/legend entry and a swap-partner label on the Layer 2
  day view. `js/nav.js` gained a "Swaps" link.
- Test script: `backend/test_swaps_ui.py` (included in this zip), same
  live-server-over-HTTP pattern as `test_leaves_ui.py`. It seeds
  deterministic master-timetable rows directly via the DB session (rather
  than `/timetables/generate`) so it has exact control over which teacher
  sits at which day/period — needed to reliably provoke the 409
  double-booking case. Covers: weekday-mismatch rejection (400), a teacher
  not involved in either slot can't request the swap (403), a teacher
  can't approve (403), a swap that *would* double-book a teacher is
  blocked on approval (409) and the admin rejects it instead (with a
  notification to the requester), a clean swap approves successfully (200)
  with notifications to both teachers, re-deciding an already-decided swap
  is rejected (400), the Layer 2 effective schedule shows the swap on the
  requested date but *not* on a different date with the same weekday, the
  master timetable itself is unchanged (Layer 1 untouched), another
  teacher can't cancel someone else's request (403), and the requester can
  cancel their own pending request (204).

  **✅ VERIFIED this session** — network access was available (unlike the
  prior two sessions), so a live sqlite-backed uvicorn server was started
  and `python backend/test_swaps_ui.py` was actually run against it:
  **all 29 checks passed** (`ALL PHASE 5 TESTS PASSED`). `test_leaves_ui.py`
  was also re-run per the note below (the `teacher_id` filter fix touches
  shared code) — **all checks passed there too**.

  What was done in the *prior* no-network session, before this one, in
  lieu of running it: a careful manual/static read-through of the three
  risk areas the previous handoff flagged, specifically:
  - The `join(...) | (...) ... .distinct()` construction in
    `list_swaps` (teacher-scoped listing) — traced through by hand: the
    `.query(models.Swap)` SELECT only projects `Swap` + the aliased
    `joinedload` columns (SQLAlchemy auto-aliases joined-eager-loads to
    avoid colliding with explicit joins), so even though the explicit
    `join(models.Timetable, id==timetable_id_a OR id==timetable_id_b)`
    can produce two physical rows per Swap, both rows select identical
    columns and `.distinct()` correctly collapses them. No bug found.
  - The `timetable_a`/`timetable_b` multi-`joinedload` chains — the
    `Swap` model correctly disambiguates both relationships with
    `foreign_keys=[...]`, avoiding the `AmbiguousForeignKeysError` this
    pattern is prone to. No bug found.
  - The `day_of_week`/`weekday()` convention — confirmed `swaps.py` uses
    `payload.date.weekday()` (Monday=0), the exact same convention
    already used by Phase 4's `leaves.py`/`substitutions.py` and by
    `Timetable.day_of_week` itself. No off-by-one found.

  This review *did* turn up one real bug, adjacent to but outside
  `swaps.py` itself: in `GET /substitutions/schedule`
  (`app/routers/substitutions.py`), the `teacher_id` query filter was
  applied at the SQL level against the *master* `Timetable.teacher_id`,
  before the Substitution/Swap overlays were resolved. That silently
  dropped any slot where a teacher only appears via an overlay (e.g. they
  swapped into someone else's period), even though the function already
  had a later Python-side check clearly intended to catch exactly that
  case — that check was unreachable dead code. Fixed by moving the
  `teacher_id` filtering to after the overlays are computed, in Python.
  This affects both the Swaps view and (retroactively) the
  already-"verified" Phase 4 Substitutions view when filtered by a
  substitute teacher's `teacher_id` — worth specifically covering in
  `test_swaps_ui.py`/`test_leaves_ui.py` re-runs.

  **Both have now been run and pass.** `python backend/test_swaps_ui.py`:
  29/29 checks passed. `python backend/test_leaves_ui.py`: all checks
  passed, including the substitution/notification flow that exercises the
  `teacher_id` filter fix. Phase 5 (and retroactively Phase 4) are
  verified end-to-end.

## Exam Module (Phase 6)

Exam scheduling: subject + section + date/start/end time, with optional
room (`resource_id`) and invigilator (`invigilator_id`). Exams are their
own table/model (not a Layer-2 overlay like Substitution/Swap) since an
exam period doesn't correspond 1:1 with a master-timetable row — it's a
separate schedule, generally on separate (non-teaching) days.

- Backend: `app/routers/exams.py` (new, purpose-built router — generation
  plus room/invigilator conflict-checking isn't plain CRUD, same rationale
  as `timetables.py`/`swaps.py`).
- Schema: no new columns needed — the pre-existing `Exam` model already had
  every field required (`subject_id`, `section_id`, `resource_id`,
  `invigilator_id`, `date`, `start_time`, `end_time`). Added (additive)
  `subject`/`section`/`resource`/`invigilator` relationships to the model
  so the router's `joinedload` chains have something to attach to.
- **Manual scheduling** (`POST /exams`, admin-only): validates `end_time >
  start_time`, then blocks (409) if the requested date/time-range overlaps
  another exam for the same section, the same room, or the same
  invigilator. Time-range overlap (not exact match) since exams have
  arbitrary start/end times, unlike the period-grid Timetable/Swap model.
  `PUT`/`DELETE` follow the same conflict rules.
- **Generator** (`POST /exams/generate`, admin-only): a deliberately
  **greedy** placement, not OR-Tools CP-SAT. Rationale documented in the
  router's module docstring — exam scheduling here only needs "don't
  double-book a section/room/invigilator", which greedy earliest-slot
  placement satisfies without needing a solver; CP-SAT would earn its
  keep if invigilator load-balancing or per-subject fixed durations get
  added later, not for v1. Algorithm:
  1. Resolve target sections (`section_ids`, or every section in the
     school).
  2. For each section, look up which subjects it's actually taught, per
     the *master* `Timetable` (`subject_id` distinct for that
     `section_id`) — this is where the "(section, subject) pairs to
     examine" come from; a section with no generated master timetable
     yet simply yields none.
  3. Build the ordered list of candidate `(date, start_time, end_time)`
     slots across the given date range, skipping weekends via the same
     `School.working_days`/`weekday()` convention used elsewhere, at
     `exams_per_day` slots/day of `duration_minutes` separated by
     `gap_minutes`.
  4. For each pair, walk the slot list and take the first slot where the
     section is free; if the subject has a fixed `resource_id` (e.g. a
     lab) that room must also be free, otherwise a free room is picked
     from `resource_ids` (or all the school's resources) if any are
     configured — if none are free/configured, `resource_id` stays null
     rather than blocking the exam (manual room assignment becomes an
     admin follow-up); an invigilator is round-robin-picked from the
     school's teachers, favoring even spread and skipping anyone already
     busy at that slot.
  5. Pairs that can't be placed anywhere in the range are reported back
     in `unscheduled` (with a reason) rather than raising — a partial
     result is more useful than an all-or-nothing failure.
  Also seeds itself with any exams already in the target date range
  (both pre-existing manual ones and from a prior generate call) so
  re-running the generator, or mixing manual + generated exams, can't
  double-book.
- Frontend: `frontend/exams.html` + `js/exams.js` — admins get a generator
  form (date range, exams/day, timing, optional section checklist), a
  manual single-exam form, and a filterable (upcoming/all) list with
  delete; teachers get a read-only upcoming/all list of exams (no
  generate/create/delete — scheduling exams is an admin action; a
  teacher's own filtered view, e.g. "exams I'm invigilating", is a
  possible follow-up but wasn't asked for explicitly, so kept out of v1
  to stay minimal). `js/nav.js` gained an "Exams" link. No new CSS was
  needed — reuses the existing form-card/tab/table classes from
  Leaves/Swaps.
- Test script: `backend/test_exams_ui.py` — same live-server-over-HTTP
  pattern as `test_leaves_ui.py`/`test_swaps_ui.py`. Seeds master-timetable
  rows directly via the DB session so the generator has real (section,
  subject) pairs to work with. Covers: non-admin can't create an exam
  (403), overlapping section/room/invigilator are each independently
  blocked (409), a non-overlapping exam succeeds (201), rescheduling into
  a conflict is blocked (409) while a genuinely non-conflicting reschedule
  succeeds (200), list/get/delete, the generator places all expected
  (section, subject) pairs with none left unscheduled in a roomy date
  range, generated exams never land on a weekend, and re-running the
  generator over a range that already has exams in it doesn't error.

  **⚠️ One real bug was found and fixed when this was run live for the
  first time this session** (both prior sessions had no network access,
  so this had genuinely never executed before). It was **not** one of the
  areas either prior static review focused on — it's a Python annotation-
  evaluation gotcha in `app/schemas.py`, `ExamUpdate`:

  ```python
  date: date | None = None
  ```

  For an annotated assignment `x: T = v` inside a class body, CPython
  evaluates and stores the *value* (`None`) into the class namespace
  **before** it evaluates the *annotation* expression (`date | None`) —
  see `dis.dis()` on that line: `STORE_NAME date` happens, then
  `LOAD_NAME date`. Because the field is named `date` — same as the
  `datetime.date` type it's annotated with — the annotation lookup found
  the freshly-stored `None` instead of the imported class, and
  `None | None` raised `TypeError: unsupported operand type(s) for |:
  'NoneType' and 'NoneType'` at import time (crashing the whole app,
  since `schemas.py` is imported by everything). This only bites a field
  when its name matches its type's name *and* it has a default assigned
  in the same statement — every other `date: date` field in the file
  (no default, annotation-only) was unaffected, which is why the earlier
  static reviews of *other* files didn't surface it. `end_date: date |
  None = None` nearby is fine too, since `end_date` doesn't collide with
  the imported name.

  Fix: added an aliased import (`from datetime import date as _date`)
  used only for this one field's annotation (`date: _date | None =
  None`), leaving every other `date`/`time` usage in the file untouched
  to minimize blast radius. Confirmed `from __future__ import
  annotations` would *not* have fixed this (tested) — pydantic v2's lazy
  annotation resolution still uses the class's own `__dict__` (which
  already contains `date: None`) as part of its lookup namespace, so the
  collision reappears at resolution time either way.

  **✅ VERIFIED this session** — `python backend/test_exams_ui.py`
  (after the fix above): **all checks passed**, including manual
  create/update/conflict-detection (all three conflict types), list/get/
  delete, and the generator (full placement, no weekend placements, safe
  re-run). Phase 6 is verified end-to-end.

## Reports (Phase 7)

Five reports, each with a JSON endpoint (for the on-screen table) and a
PDF/Excel export endpoint with the same filters. Admin-only (super_admin/
school_admin) — these aggregate across an entire school, not a teacher's
own data. Purpose-built router (`app/routers/reports.py`), same rationale
as `timetables.py`/`swaps.py`/`exams.py`: aggregation + file export isn't
plain CRUD. Export rendering lives in `app/services/report_export.py`
(reportlab for PDF, openpyxl for Excel — added to `requirements.txt`),
kept as two generic shapes (a plain table, and a day/period grid for the
Timetables report) so all five reports share the same rendering code.

- **Teacher Workload** (`GET /reports/teacher-workload`) — per teacher:
  periods/week actually scheduled on the master timetable (`Timetable`
  rows where `teacher_id` is set and it's a subject lesson, not an
  activity), against `Teacher.max_weekly_hours`, as a utilization %;
  distinct sections/subjects taught; flagged `overloaded` if scheduled
  periods exceed the configured max. Sorted busiest-first.
- **Subject Coverage** (`GET /reports/subject-coverage`) — for every
  (section, subject) pair that appears anywhere in that section's master
  timetable: `Subject.weekly_hours` (the *required* periods/week — this is
  the same number the OR-Tools generator itself targets per section, see
  `timetable_generator.py`) against periods actually scheduled for that
  section, as a coverage % and a raw gap count. Sorted worst-coverage-
  first, so shortfalls surface immediately.
- **Resource Usage** (`GET /reports/resource-usage`) — for every
  `Resource`: master-timetable bookings/week (`Timetable.resource_id`
  count) and exam bookings (`Exam.resource_id` count), plus a
  utilization % against the school's theoretical max slots/week
  (`periods_per_day × working_days`). Flags entirely-unused resources.
- **Leave Summary** (`GET /reports/leave-summary?start_date=&end_date=`,
  defaults to the trailing 30 days) — request counts by status, and a
  per-teacher breakdown (requests/approved/pending/rejected, approved
  days actually falling inside the range). Also computes a **coverage
  rate**: for every approved leave's dates inside the range, re-derives
  which of that teacher's scheduled slots on that weekday got a real
  `Substitution` row (same `Timetable`-lookup approach as
  `leaves.py`'s `GET /leaves/{id}/gaps`, just aggregated across every
  leave in range instead of one) — this is a genuine re-derivation from
  live data, not a stored counter, so it stays correct even if
  substitutions are edited/deleted after the fact.
- **Timetables** (`GET /reports/timetable?section_id=` or `?teacher_id=`)
  — a formatted day/period grid for one section or one teacher (mirrors
  the Timetable Viewer's section-grid/teacher-grid, just export-shaped);
  requires exactly one of `section_id`/`teacher_id`, 404s if that
  section/teacher has no master-timetable rows yet.
- **Export**: `GET /reports/export/<report>?format=pdf|xlsx` (plus the
  same filters as the JSON endpoint) streams back a real file with the
  right `Content-Type`/`Content-Disposition` — no temp files on disk.
  Every export is also written to the audit log (`export_report` action).
- Frontend: `frontend/reports.html` + `js/reports.js` — a tab per report
  (school selector for super_admin, like Exams), each rendering the JSON
  as a table plus "Export PDF"/"Export Excel" buttons. Export buttons
  can't reuse `apiRequest` (it always parses JSON) — `downloadReport()`
  does its own authenticated `fetch()`, reads the filename back out of
  `Content-Disposition`, and triggers a browser download via a
  synthetic `<a download>`. The Timetables tab reuses `table.tt-grid`
  styling from the Timetable Viewer. `js/nav.js` gained a "Reports" link.
  No new CSS needed.
- Test script: `backend/test_reports_ui.py` — builds a small school with
  a real generated master timetable (via `/timetables/generate`, actual
  OR-Tools), takes and approves a real leave (for genuine leave-summary
  coverage data), schedules a real exam against a resource (for genuine
  resource-usage exam-booking data), then exercises all five JSON
  endpoints plus both export formats for each, role-gating (teacher
  gets 403), the super_admin-without-`school_id` 400, the
  neither-`section_id`-nor-`teacher_id` 400 on the Timetables report,
  and the 404 for a nonexistent section export.

  **✅ VERIFIED this session** — network access was available, so this
  was run against a live server from the start (no code shipped
  unverified this time): **all checks passed** on the first run. PDF/
  Excel output was also independently spot-checked outside the test
  script (`file` command confirms valid `PDF document, version 1.4` and
  `Microsoft Excel 2007+` output).

## Groq-Powered Assistant & Dashboard settings (Phase 8)

The AI assistant and school administration settings are fully integrated.
- **Explain conflict**: In-app scheduling conflicts (e.g., 409/422 responses) can be fed to Groq to generate a user-friendly, plain-English explanation.
- **Workload suggestions**: Analyzes teacher workloads and subject scheduling coverage to provide actionable recommendations. Returns a canned "healthy" response without hitting the LLM if everything is fully covered and balanced.
- **Report narration**: Generates a professional narrative summary of any school report (workload, coverage, resource usage, leave summary, or timetables) alongside its table.
- **Admin Chat Assistant**: A floating chat widget available site-wide to administrators (`super_admin` and `school_admin`), offering free-form Q&A with access to real-time reports via registered tools.
- **Multi-Tenant Settings Update**: Modified the PUT `/schools/{id}` endpoint to allow `school_admin` users to edit settings for their own school context (re-scoping details like school name, address, periods per day, and working days) while blocking them from other schools, and reserving create/delete access exclusively for `super_admin`.

All features are fully verified end-to-end against a fresh database, with 6 integration tests running back-to-back successfully.
