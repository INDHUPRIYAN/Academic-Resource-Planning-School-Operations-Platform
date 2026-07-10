# EduFlow AI — Universal Platform Implementation Plan

> **STATUS: REQUIREMENTS LOCKED — Awaiting user "proceed" command before implementation begins.**
> 
> Every phase will follow the 9-step milestone workflow: Inspect → Impact Analysis → Plan → Implement → Integration Review → Feature Audit → Logical Tests → Stabilize → Completion Report.

---

## Phase 1: Universal Configuration Engine ✅ (Partially Complete)

### Goal
Convert EduFlow AI from a fixed-workflow app into a configuration-driven platform.

### Already Done
- `SchoolConfig` model + `GET/PUT /schools/{id}/config`
- `SubjectAssignment` CRUD (`/assignments`)
- `TeachingGroup` model
- `CalendarEvent` model + CRUD (`/calendar`)
- 6 preset templates (Government, Private, CBSE, ICSE, Matriculation, Higher Secondary) + `POST /schools/{id}/apply-template`
- Setup Wizard (5-step onboarding)
- OR-Tools solver reads config dynamically (manual/hybrid/auto modes, PET timing, max consecutive, resource toggle)

### Remaining
- [ ] Period timings in config (`[{"period": 1, "start": "09:00", "end": "09:45"}]`)
- [ ] Academic year label in config
- [ ] `enabled_modules` list in config
- [ ] Configuration Editor UI (`config_editor.html` / `config_editor.js`) — tabbed panel
- [ ] Calendar management UI (`calendar.html` / `calendar.js`)
- [ ] Template selector integrated into Setup Wizard
- [ ] Nav bar links for Configuration Editor and Calendar

---

## Phase 2: Dynamic UI Engine

### Goal
Remove unnecessary fields. Forms adapt automatically based on school configuration.

### Requirements
- Resources Disabled → Hide entire Resource module (nav, forms, selectors, reports)
- Activities Disabled → Hide Activities module entirely
- Medium Disabled → Hide Medium selection fields
- Manual Assignment Disabled → Hide Assignment Grid
- Teacher Groups Disabled → Hide Teaching Group configuration
- Exams Disabled → Hide Exams nav/pages
- Every page must dynamically check `SchoolConfig` on load
- Administrator should **never** ask "What should I fill here?"

### Testing Matrix
- [ ] Government School (resources off, activities off, manual assignment)
- [ ] Private School (everything on, automatic assignment)
- [ ] Minimal School (bare minimum config)
- [ ] Advanced School (all features enabled)

---

## Phase 3: Universal Scheduler

### Goal
Remove every hardcoded assumption from the OR-Tools solver.

### Scheduler Must Read
- School Profile (periods, days, type)
- Workflow Profile (assignment method, substitution policy)
- Teacher Policies (max hours, availability, groups)
- Teaching Groups (wing restrictions)
- Activities (PET, Library, etc. with preferred periods)
- Resources (labs, rooms, grounds — collision avoidance)
- Academic Calendar (skip holidays, exam weeks)
- Scheduling Policies (all configurable rules)
- Teaching Assignments (manual/hybrid mappings)

### Supported Modes
- Automatic — solver picks teachers
- Manual — solver uses explicit assignments only
- Hybrid — solver respects manual + auto-fills rest
- Conflict-check only — validate existing schedule without regenerating

### Testing Matrix
- [ ] School with Resources / without Resources
- [ ] School with Activities / without Activities
- [ ] Primary school only
- [ ] Higher Secondary only
- [ ] Multiple Mediums
- [ ] Single Medium

---

## Phase 4: Policy Engine

### Goal
Replace all hardcoded scheduling rules with a database-driven policy engine.

### Policies (each: enabled/disabled/editable)
- PET Last Period
- Science Practical Consecutive
- Assembly First Period
- Double Period Blocks
- Lunch Break Placement
- Teacher Preferences (preferred periods, avoided periods)
- No Subject Repetition Same Day
- Max Consecutive Periods
- Max Daily Periods per Teacher
- Max Weekly Periods per Teacher

### Implementation
- Store policies in `SchoolConfig.config` JSON under `scheduling_policies`
- Solver reads each policy flag and conditionally applies constraints
- Configuration Editor exposes toggles for each policy

### Testing
- [ ] Each policy individually enabled/disabled
- [ ] Combinations of policies
- [ ] Policy conflicts (mutually exclusive rules)

---

## Phase 5: Validation Engine

### Goal
Before timetable generation, automatically validate the school's readiness.

### Pre-Generation Checks
- Teacher missing for assigned subject
- Weekly hours not defined for a subject
- Resource missing for a subject that requires it
- Assignments missing (in manual/hybrid mode)
- Teacher overloaded (assigned hours exceed max)
- Invalid or incomplete configuration
- Section without any subjects
- Class without sections

### Output Format
For each issue:
- **Problem** — what's wrong
- **Reason** — why it matters
- **How to Fix** — actionable guidance
- **Auto Fix** — apply fix automatically (if possible)

### Testing
- [ ] Schools with deliberately invalid/incomplete data
- [ ] Schools with valid data (should pass cleanly)

---

## Phase 6: Conflict Resolution Center

### Goal
Instead of "Generation Failed", show actionable conflict diagnostics.

### Conflict Display
- Conflict description
- Reason (e.g. "Teacher Murugan is assigned to 2 sections at Period 3, Monday")
- Affected Classes
- Affected Teachers
- Suggested Solution
- Auto Fix button (if applicable)
- Manual Fix guidance
- Impact analysis

### Conflict Types
- Resource clash (lab double-booked)
- Teacher clash (teacher double-booked)
- Subject clash (hours impossible to fit)
- Impossible schedule (infeasible constraint set)

### Testing
- [ ] Each conflict type individually
- [ ] Multiple simultaneous conflicts

---

## Phase 7: Leave & Operational Layer

### Goal
Master timetable is immutable. All day-to-day changes go through an operational overlay.

### Operational Layer Stores
- Leaves (approved teacher absences)
- Substitutions (replacement teacher assignments)
- Swaps (period exchanges between teachers)
- Exam Changes (schedule modifications during exam weeks)
- Holiday Changes (cancelled classes due to holidays)
- Special Events (assembly, sports day, etc.)

### Rule
Master timetable **never** changes after publication. All modifications are overlay records scoped to specific dates.

### Testing
- [ ] Teacher leave → substitute assigned → schedule reflects substitute
- [ ] Emergency leave (same day)
- [ ] Multiple teachers on leave same day
- [ ] Teacher swap
- [ ] Exam week schedule override
- [ ] Holiday → classes auto-cancelled

---

## Phase 8: Academic Calendar

### Goal
Full calendar support integrated with the scheduler and operational layer.

### Calendar Events
- Working Days
- Working Saturdays
- Exam Weeks
- Sports Week
- Festival Holidays
- Special Events (Annual Day, PTA)
- Emergency Holidays (e.g. election duty, natural disaster)

### Integration
- Scheduler skips holiday dates during operational schedule generation
- Leave engine checks calendar before approving
- Reports factor in actual working days
- Dashboard shows upcoming events

### Testing
- [ ] Holiday → classes cancelled
- [ ] Exam week → modified schedule
- [ ] Annual Day → special event handling

---

## Phase 9: Draft Workflow

### Goal
Support timetable versioning with publication control.

### Timetable States
- **Draft** — work in progress, editable, not visible to teachers
- **Published** — active schedule, immutable, visible to all
- **Archived** — historical record, read-only

### Rules
- Never overwrite a published timetable
- New generation creates a new draft
- Admin reviews draft → publishes → old published moves to archived
- Operational layer always reads from the currently published version

### Database Change
- Add `version_id` and `status` columns to `Timetable` or create `TimetableVersion` table

### Testing
- [ ] Create draft → edit → publish
- [ ] Create new draft while published exists
- [ ] Verify published is immutable
- [ ] Verify archived is read-only
- [ ] Operational layer reads correct version

---

## Phase 10: Bulk Import

### Goal
Import school data from CSV/Excel files with pre-import validation.

### Importable Entities
- Teachers
- Subjects
- Classes
- Sections
- Assignments (section-subject-teacher mappings)
- Resources
- Future: Students

### Supported Formats
- CSV
- Excel (.xlsx)

### Workflow
1. Upload file
2. Validate all rows (show errors per row)
3. Preview valid data
4. Confirm import
5. Rollback on failure

### Already Done
- Bulk upload page (`bulk.html` / `bulk.js`) with multi-sheet Excel support
- Backend template generation + import endpoints

### Remaining
- [ ] CSV support
- [ ] Assignments sheet in bulk import
- [ ] Pre-import validation summary UI
- [ ] Large dataset stress test

---

## Phase 11: Reports

### Goal
Dynamic, module-aware reporting engine.

### Rules
- Only show reports for enabled modules
- Disabled modules produce no report tabs

### Report Types
- Teacher Workload
- Subject Coverage
- Resource Utilization (if resources enabled)
- Activity Coverage (if activities enabled)
- Leave Summary
- Timetable Export
- Health Report (overall school readiness)

### Export Formats
- PDF
- Excel (.xlsx)

### Already Done
- Reports page with dynamic tab filtering based on config
- PDF/Excel export endpoints
- AI narration of reports via Groq

### Remaining
- [ ] Health Report tab
- [ ] Activity-specific reports
- [ ] Fully module-aware tab filtering for all new modules

---

## Phase 12: Health Dashboard

### Goal
Dashboard displays school readiness scores and actionable warnings.

### Metrics
| Metric | Example |
|---|---|
| Configuration Score | 97% |
| Teacher Assignments | 100% |
| Subjects Configured | 100% |
| Resources Configured | 80% |
| Calendar Populated | 60% |
| Warnings | 2 |
| Overall Readiness | Ready / Not Ready |

### Implementation
- New API endpoint: `GET /schools/{id}/health`
- Computes scores by checking completeness of config, assignments, subjects, teachers, resources
- Dashboard card shows scores with color-coded indicators
- Warnings link to the specific page to fix the issue

---

## Phase 13: Explainable Scheduler

### Goal
Instead of "Failed", explain **why**.

### Examples
- "Teacher Murugan — Maximum weekly hours (30) exceeded. Currently assigned 34 hours."
- "Science Lab — Already occupied by Grade 9A at Period 4, Monday."
- "No qualified substitute available for English on Tuesday."

### Implementation
- Solver captures constraint violation details during search
- API returns structured error list with affected entities
- Frontend renders conflict cards with explanations
- Groq used **only** to explain and summarize — **never** to generate timetables

---

## Phase 14: School Templates

### Goal
One-click school setup from preset templates.

### Templates
- Government School
- Private School
- CBSE
- ICSE
- Matriculation
- Higher Secondary
- College
- Coaching Institute
- Custom (blank slate)

### Workflow
1. Admin selects template during onboarding
2. Everything auto-configures (grades, sections, policies, modules)
3. Admin edits later through Configuration Editor

### Already Done
- 6 templates defined in backend (`schools.py`)
- `POST /schools/{id}/apply-template` endpoint

### Remaining
- [ ] Add College, Coaching Institute, Custom templates
- [ ] Template selector in Setup Wizard Step 1
- [ ] Template preview before applying

---

## Phase 15: Plugin Architecture

### Goal
Future modules plug in without redesigning the project.

### Future Modules
- Attendance
- Fees
- Transport
- Hostel
- Library Management
- Biometric Integration
- Parent App
- Student App
- AI Analytics

### Architecture
- Each module is a self-contained router + model + frontend page
- Module registration in `enabled_modules` config
- Frontend dynamically loads only enabled module pages/nav links
- Backend skips disabled module routes
- No core code changes required to add a new module

---

## Universal Testing Phase

### Architecture Audit
- [ ] Folder structure review
- [ ] Database schema review
- [ ] API completeness review
- [ ] Scheduler constraint coverage
- [ ] Service layer review
- [ ] Frontend module review

### Functional Testing — Create 10 School Profiles

| School | Type | Assignment | Medium | Resources | Activities |
|---|---|---|---|---|---|
| A | Government | Manual | Tamil + English | Off | Off |
| B | Private | Automatic | English | On | On |
| C | CBSE | Hybrid | English | On | On |
| D | Primary Only | Automatic | English | Off | Off |
| E | Higher Secondary | Manual | Tamil + English | On | Off |
| F | Tamil Medium Only | Manual | Tamil | Off | Off |
| G | English Medium Only | Automatic | English | On | On |
| H | Multiple Mediums | Hybrid | English + Tamil + Hindi | On | On |
| I | Resources Disabled | Automatic | English | Off | On |
| J | Activities Disabled | Hybrid | English | On | Off |

- [ ] Verify every school's timetable generates correctly
- [ ] Verify UI adapts for each school's config
- [ ] Verify reports match enabled modules

### Scheduler Stress Testing
- [ ] Generate 100+ timetables across all school profiles
- [ ] Verify: No teacher clashes, no resource clashes, hours satisfied, activities satisfied, calendar respected, leaves handled, substitutes handled, swaps handled

### Scale Testing

| Scenario | Teachers | Classes |
|---|---|---|
| Small | 20 | 10 |
| Medium | 50 | 30 |
| Large | 100 | 100 |

- [ ] Measure generation time, memory usage, DB query count, API response times

### Code Quality Audit
- [ ] No duplicate code
- [ ] No oversized files (>500 lines flagged)
- [ ] Reusable components and services
- [ ] Clean architecture
- [ ] No dead code

### Security Audit
- [ ] JWT validation
- [ ] Role-based permissions
- [ ] Input validation (Pydantic schemas)
- [ ] SQL injection prevention (ORM-only queries)
- [ ] XSS prevention
- [ ] Environment variables for secrets
- [ ] Audit log coverage

---

## Final Acceptance Criteria

The implementation is complete **only if**:

1. Every feature works end-to-end
2. Every page is connected to the backend
3. No static or placeholder data remains
4. Existing features continue to work
5. The platform supports multiple school workflows through configuration
6. The scheduler is configuration-driven and policy-driven
7. The administrator only sees fields relevant to their school's configuration
8. Published timetables remain immutable; operational changes go through the operational layer
9. All modules pass integration and regression testing
10. The codebase remains modular, maintainable, scalable, and production-ready

---

## Execution Rules

Before implementing each phase:
1. Inspect existing implementation
2. Identify reusable code
3. Prepare implementation plan
4. Implement only required changes
5. Run automated and logical tests
6. Fix any issues found
7. Perform regression test
8. Provide completion report
9. **Do not proceed to next phase until current phase is fully functional, tested, and stable**
