"""
Layer 1 (Master Timetable) generator, built on Google OR-Tools CP-SAT.

Never used for anything the spec calls out as AI territory (conflict
explanations, workload suggestions, etc.) - this module is pure constraint
programming, deterministic given the same input data.

Design notes / scope (documented honestly rather than silently assumed):
- A school's subjects/activities are treated as taught in every section of
  that school, at the subject's/activity's configured weekly_hours - there is
  no per-section subject list in the current schema, so this is the only
  interpretation the data model supports.
- Locked rows (is_locked=True) are treated as hard pre-assignments: the
  solver leaves that exact (section, day, period) slot untouched and blocks
  any other lesson from using that slot's teacher/resource at that time.
  Regeneration only replaces unlocked rows.
- Resource conflicts are enforced only for subjects/activities that declare
  a resource_id (e.g. a Chemistry subject pointing at a "Lab" resource).
  Subjects/activities without a resource_id are assumed not to need a
  dedicated room and never conflict on resources.
"""
from dataclasses import dataclass, field
from ortools.sat.python import cp_model
from sqlalchemy.orm import Session, joinedload
from datetime import timedelta

from app import models


class TimetableGenerationError(ValueError):
    """Raised for any condition that makes generation impossible - bad input
    data or genuine infeasibility - with a message safe to show an admin."""


@dataclass
class GeneratedSlot:
    section_id: int
    day_of_week: int
    period: int
    subject_id: int | None = None
    teacher_id: int | None = None
    activity_id: int | None = None
    resource_id: int | None = None


@dataclass
class GenerationResult:
    slots: list[GeneratedSlot]
    sections_scheduled: int
    optimal: bool


import json

DEFAULT_CONFIG = {
    "institution_type": "school",  # "school" | "college" - engine behaviour is fully config-driven
    "school_type": "Other",
    "academic_structure": {"grades": []},
    "sections_per_grade": {},
    "mediums": {"enabled": False, "list": []},
    "teacher_assignment_method": "automatic",
    "teacher_eligibility": {"enabled": False, "groups": []},
    "subject_configuration": {"hours_defined_at": "per_class"},
    "activities": {"enabled": False, "list": []},
    "resources": {"enabled": True},
    "substitution_policy": "automatic",
    "scheduling_policies": {
        "max_consecutive_periods": 3,
        "max_daily_periods": 8,
        "double_periods_allowed": False,
        "science_practical_consecutive": False,
        "pet_last_periods": False
    }
}

def generate_master_timetable(db: Session, school_id: int, time_limit_seconds: int = 30) -> GenerationResult:
    school = db.query(models.School).filter(models.School.id == school_id).first()
    if not school:
        raise TimetableGenerationError("School not found")

    # Load calendar events and filter holidays to exclude from days pool
    holidays = db.query(models.CalendarEvent).filter(
        models.CalendarEvent.school_id == school_id,
        models.CalendarEvent.is_holiday.is_(True)
    ).all()
    
    blocked_weekdays = set()
    for h in holidays:
        start = h.date
        end = h.end_date or h.date
        curr = start
        while curr <= end:
            # weekday() returns 0 for Monday, ..., 6 for Sunday
            blocked_weekdays.add(curr.weekday())
            curr += timedelta(days=1)

    days = [d for d in list(range(school.working_days)) if d not in blocked_weekdays]
    if not days:
        days = list(range(school.working_days))

    periods = list(range(1, school.periods_per_day + 1))
    if not days or not periods:
        raise TimetableGenerationError("School has no working days / periods configured")

    sections = (
        db.query(models.Section)
        .join(models.Class, models.Section.class_id == models.Class.id)
        .filter(models.Class.school_id == school_id)
        .all()
    )
    if not sections:
        raise TimetableGenerationError("No sections found for this school - add classes/sections first")

    subjects = db.query(models.Subject).filter(models.Subject.school_id == school_id).all()
    activities = db.query(models.Activity).filter(models.Activity.school_id == school_id).all()
    if not subjects and not activities:
        raise TimetableGenerationError("No subjects or activities found for this school")

    teachers = (
        db.query(models.Teacher)
        .options(joinedload(models.Teacher.subjects), joinedload(models.Teacher.teaching_group))
        .filter(models.Teacher.school_id == school_id)
        .all()
    )

    # 1. Load dynamic school configuration and assignments
    config_row = db.query(models.SchoolConfig).filter(models.SchoolConfig.school_id == school_id).first()
    config = json.loads(config_row.config) if config_row else DEFAULT_CONFIG
    
    assignments = (
        db.query(models.SubjectAssignment)
        .options(joinedload(models.SubjectAssignment.subject))
        .filter(models.SubjectAssignment.school_id == school_id)
        .all()
    )

    # Load teacher availabilities
    availabilities = db.query(models.TeacherAvailability).filter(
        models.TeacherAvailability.teacher_id.in_([t.id for t in teachers])
    ).all()
    teacher_avail_map = {(a.teacher_id, a.day_of_week, a.period): a.is_available for a in availabilities}

    # Load teacher preferences
    preferences = db.query(models.TeacherPreference).filter(
        models.TeacherPreference.teacher_id.in_([t.id for t in teachers])
    ).all()

    # Load teacher eligibility allowed grades
    teacher_allowed_grades = {}
    if config.get("teacher_eligibility", {}).get("enabled", False):
        for t in teachers:
            if t.teaching_group:
                grades = [g.strip() for g in t.teaching_group.allowed_grades.split(",") if g.strip()]
                teacher_allowed_grades[t.id] = set(grades)

    # Map allowed teachers and hours per section/subject
    sec_subject_teachers = {}
    sec_subject_hours = {}
    method = config.get("teacher_assignment_method", "automatic")

    if method in ("manual", "hybrid") and assignments:
        for ass in assignments:
            key = (ass.section_id, ass.subject_id)
            if config.get("subject_configuration", {}).get("hours_defined_at") == "per_section":
                sec_subject_hours[key] = ass.weekly_hours_override if ass.weekly_hours_override is not None else ass.subject.weekly_hours
            else:
                sec_subject_hours[key] = ass.subject.weekly_hours
            
            allowed_t = []
            if ass.teacher_id:
                allowed_t = [ass.teacher_id]
            elif method == "hybrid":
                allowed_t = [t.id for t in teachers if ass.subject in t.subjects]
                
            # Filter by teaching wing eligibility
            sec_obj = next((s for s in sections if s.id == ass.section_id), None)
            if sec_obj and allowed_t:
                filtered_t = []
                for tid in allowed_t:
                    if tid in teacher_allowed_grades:
                        if sec_obj.class_.name not in teacher_allowed_grades[tid]:
                            continue
                    filtered_t.append(tid)
                allowed_t = filtered_t
                
            sec_subject_teachers[key] = allowed_t
    else:
        # Automatic mode / backward-compatible fallback
        for sec in sections:
            for subj in subjects:
                key = (sec.id, subj.id)
                ass = next((a for a in assignments if a.section_id == sec.id and a.subject_id == subj.id), None)
                if config.get("subject_configuration", {}).get("hours_defined_at") == "per_section" and ass:
                    sec_subject_hours[key] = ass.weekly_hours_override if ass.weekly_hours_override is not None else subj.weekly_hours
                else:
                    sec_subject_hours[key] = subj.weekly_hours
                allowed_t = [t.id for t in teachers if subj in t.subjects]
                
                # Filter by teaching wing eligibility
                filtered_t = []
                for tid in allowed_t:
                    if tid in teacher_allowed_grades:
                        if sec.class_.name not in teacher_allowed_grades[tid]:
                            continue
                    filtered_t.append(tid)
                sec_subject_teachers[key] = filtered_t

    # Validate that every requested subject has at least one eligible teacher
    for (sec_id, subj_id), hours in sec_subject_hours.items():
        if hours > 0 and not sec_subject_teachers.get((sec_id, subj_id)):
            sec_obj = next(s for s in sections if s.id == sec_id)
            subj_obj = next(s for s in subjects if s.id == subj_id)
            raise TimetableGenerationError(
                f"No teacher is assigned/eligible to teach subject '{subj_obj.name}' in section "
                f"'{sec_obj.class_.name} {sec_obj.name}'."
            )

    # 2. Check weekly hours limits per section
    total_slots_per_section = len(days) * len(periods)
    for sec in sections:
        sec_required = sum(sec_subject_hours.get((sec.id, s.id), 0) for s in subjects) + sum(a.weekly_hours for a in activities)
        if sec_required > total_slots_per_section:
            raise TimetableGenerationError(
                f"Required weekly periods ({sec_required}) for section '{sec.class_.name} {sec.name}' "
                f"exceed the {total_slots_per_section} available slots."
            )

    # 2b. Lint the subject-spread policy before solving. PolicyEngine caps a subject at one
    # lesson per day (two when double periods are allowed), so weekly_hours above that ceiling
    # is unsatisfiable. Catch it here: the solver would only report a generic "infeasible".
    policies = config.get("scheduling_policies", {})
    max_lessons_per_day = 2 if policies.get("double_periods_allowed", False) else 1
    spread_ceiling = max_lessons_per_day * len(days)
    for sec in sections:
        for subj in subjects:
            hours = sec_subject_hours.get((sec.id, subj.id), 0)
            if hours > spread_ceiling:
                raise TimetableGenerationError(
                    f"Subject '{subj.name}' needs {hours} weekly periods in section "
                    f"'{sec.class_.name} {sec.name}', but the subject-spread policy allows at most "
                    f"{max_lessons_per_day} lesson(s) per day across {len(days)} teaching day(s) "
                    f"(= {spread_ceiling}). Either reduce '{subj.name}' to {spread_ceiling} weekly "
                    f"hours, enable 'double_periods_allowed' in scheduling policies, or add a teaching day."
                )

    # 2c. Lint teacher capacity. When a subject/section has exactly one eligible teacher
    # (always true in manual assignment mode) that teacher's load is forced, so an over-cap
    # allocation is unsatisfiable. Name the teacher instead of blaming "not enough teachers".
    teacher_by_id = {t.id: t for t in teachers}
    grid_slots = len(days) * len(periods)
    forced_load: dict[int, int] = {}
    for (sec_id, subj_id), hours in sec_subject_hours.items():
        allowed = sec_subject_teachers.get((sec_id, subj_id), [])
        if hours > 0 and len(allowed) == 1:
            forced_load[allowed[0]] = forced_load.get(allowed[0], 0) + hours

    for t_id, needed in forced_load.items():
        t = teacher_by_id.get(t_id)
        if not t:
            continue
        t_name = t.user.name if t.user else f"Teacher {t_id}"
        if needed > t.max_weekly_hours:
            raise TimetableGenerationError(
                f"Teacher '{t_name}' is allocated {needed} weekly periods but their maximum is "
                f"{t.max_weekly_hours}. Raise their max weekly hours, or move "
                f"{needed - t.max_weekly_hours} period(s) to another teacher."
            )
        if needed > grid_slots:
            raise TimetableGenerationError(
                f"Teacher '{t_name}' is allocated {needed} weekly periods, but the timetable only "
                f"has {grid_slots} slots ({len(days)} day(s) x {len(periods)} period(s))."
            )

    # 2d. Lint subject-level capacity: total demand vs the combined caps of every teacher
    # able to teach it. A necessary condition, so a failure here is always real.
    subject_demand: dict[int, int] = {}
    subject_pool: dict[int, set[int]] = {}
    for (sec_id, subj_id), hours in sec_subject_hours.items():
        if hours <= 0:
            continue
        subject_demand[subj_id] = subject_demand.get(subj_id, 0) + hours
        subject_pool.setdefault(subj_id, set()).update(sec_subject_teachers.get((sec_id, subj_id), []))

    for subj_id, demand in subject_demand.items():
        capacity = sum(
            teacher_by_id[t_id].max_weekly_hours
            for t_id in subject_pool.get(subj_id, ())
            if t_id in teacher_by_id
        )
        if demand > capacity:
            s_name = next((s.name for s in subjects if s.id == subj_id), f"Subject {subj_id}")
            raise TimetableGenerationError(
                f"'{s_name}' needs {demand} weekly periods across all sections, but the teachers "
                f"allocated to it can cover only {capacity}. Add another '{s_name}' teacher, or "
                f"raise the max weekly hours of the existing ones."
            )

    # ---- existing locked rows: hard pre-assignments the solver must respect ----
    locked_rows = (
        db.query(models.Timetable)
        .filter(models.Timetable.school_id == school_id, models.Timetable.is_locked.is_(True))
        .all()
    )
    locked_by_slot: dict[tuple[int, int, int], models.Timetable] = {
        (r.section_id, r.day_of_week, r.period): r for r in locked_rows
    }
    locked_teacher_slots = {(r.teacher_id, r.day_of_week, r.period) for r in locked_rows if r.teacher_id}
    locked_resource_slots = {(r.resource_id, r.day_of_week, r.period) for r in locked_rows if r.resource_id}
    
    locked_subject_hours: dict[tuple[int, int], int] = {}
    locked_activity_hours: dict[tuple[int, int], int] = {}
    for r in locked_rows:
        if r.subject_id:
            key = (r.section_id, r.subject_id)
            locked_subject_hours[key] = locked_subject_hours.get(key, 0) + 1
        if r.activity_id:
            key = (r.section_id, r.activity_id)
            locked_activity_hours[key] = locked_activity_hours.get(key, 0) + 1
            
    locked_teacher_hours: dict[int, int] = {}
    for r in locked_rows:
        if r.teacher_id:
            locked_teacher_hours[r.teacher_id] = locked_teacher_hours.get(r.teacher_id, 0) + 1

    # 2e. Lint teacher availability. Availability is a hard constraint, so a teacher whose open
    # slots cannot hold the lessons allocated to them makes the model infeasible. Name the
    # teacher and the class rather than emitting a bare "no solution".
    def _teacher_open_slots(t_id: int) -> dict[int, list[int]]:
        return {
            d: [
                p for p in periods
                if teacher_avail_map.get((t_id, d, p), True) is not False
                and (t_id, d, p) not in locked_teacher_slots
            ]
            for d in days
        }

    for t in teachers:
        needed = forced_load.get(t.id, 0)
        if needed <= 0:
            continue
        open_total = sum(len(v) for v in _teacher_open_slots(t.id).values())
        if needed > open_total:
            t_name = t.user.name if t.user else f"Teacher {t.id}"
            raise TimetableGenerationError(
                f"Teacher '{t_name}' is allocated {needed} weekly periods but is available for "
                f"only {open_total} of the {len(days) * len(periods)} slots. Free up "
                f"{needed - open_total} more period(s) in their availability, or move classes "
                f"to another teacher."
            )

    # A subject may not exceed max_lessons_per_day within one section, so a teacher's
    # availability must offer enough *days*, not merely enough slots.
    for (sec_id, subj_id), hours in sec_subject_hours.items():
        allowed = sec_subject_teachers.get((sec_id, subj_id), [])
        if hours <= 0 or len(allowed) != 1:
            continue
        t_id = allowed[0]
        t = teacher_by_id.get(t_id)
        if not t:
            continue
        open_by_day = _teacher_open_slots(t_id)
        placeable = sum(
            min(max_lessons_per_day, len([p for p in open_by_day[d] if (sec_id, d, p) not in locked_by_slot]))
            for d in days
        )
        still_needed = hours - locked_subject_hours.get((sec_id, subj_id), 0)
        if still_needed > placeable:
            sec_obj = next(s for s in sections if s.id == sec_id)
            subj_obj = next(s for s in subjects if s.id == subj_id)
            t_name = t.user.name if t.user else f"Teacher {t_id}"
            raise TimetableGenerationError(
                f"'{subj_obj.name}' needs {still_needed} periods in section "
                f"'{sec_obj.class_.name} {sec_obj.name}', but '{t_name}' can be given at most "
                f"{placeable}: their availability allows only {max_lessons_per_day} lesson(s) per "
                f"day on the days they are free. Widen their availability, enable double periods, "
                f"or allocate this class to another teacher."
            )

    # 2f. Lint the daily core-subject coverage policy. Core weekly hours must fit inside
    # max_core_per_day, and must be plentiful enough to satisfy min_core_per_day.
    from app.services.policy_engine import PolicyEngine as _PolicyEngine

    core_names = policies.get("core_subjects") or []
    min_core = policies.get("min_core_per_day")
    max_core = policies.get("max_core_per_day")
    core_ids = _PolicyEngine.core_subject_ids(config, subjects)

    if core_names and (min_core is not None or max_core is not None):
        known = {s.name.strip().lower() for s in subjects}
        unknown = [n for n in core_names if str(n).strip().lower() not in known]
        if unknown:
            raise TimetableGenerationError(
                f"Core subject(s) {', '.join(map(str, unknown))} are listed in scheduling policies "
                f"but do not exist in this school. Fix the 'core_subjects' list in the configuration."
            )
        if min_core is not None and max_core is not None and min_core > max_core:
            raise TimetableGenerationError(
                f"min_core_per_day ({min_core}) cannot exceed max_core_per_day ({max_core})."
            )

        for sec in sections:
            free_by_day = {
                d: len([p for p in periods if (sec.id, d, p) not in locked_by_slot]) for d in days
            }
            core_demand = sum(sec_subject_hours.get((sec.id, sid), 0) for sid in core_ids)
            label = f"{sec.class_.name} {sec.name}"

            if max_core is not None:
                ceiling = sum(min(max_core, free_by_day[d]) for d in days)
                if core_demand > ceiling:
                    viable = next(
                        (m for m in range(1, len(periods) + 1)
                         if sum(min(m, free_by_day[d]) for d in days) >= core_demand),
                        None,
                    )
                    hint = (f"Raise max_core_per_day to at least {viable}"
                            if viable else "Reduce core subject weekly hours or add a teaching day")
                    raise TimetableGenerationError(
                        f"Section '{label}' needs {core_demand} core periods per week "
                        f"({', '.join(str(n) for n in core_names)}), but max_core_per_day="
                        f"{max_core} allows at most {ceiling} across {len(days)} day(s) "
                        f"(short by {core_demand - ceiling}). {hint}, reduce core weekly hours, "
                        f"or add non-core subjects to fill the remaining periods."
                    )

            if min_core is not None:
                floor = sum(min_core for d in days if free_by_day[d] > 0)
                if core_demand < floor:
                    raise TimetableGenerationError(
                        f"Section '{label}' has only {core_demand} core periods per week, but "
                        f"min_core_per_day={min_core} requires at least {floor} across "
                        f"{len(days)} teaching day(s). Lower min_core_per_day or increase core "
                        f"subject weekly hours."
                    )

    # 2g. Lint the per-core-subject daily minimum. A core subject can only appear every day
    # if it has enough weekly hours AND its teacher is available on every day.
    core_daily_min = policies.get("core_subject_daily_min")
    if core_ids and core_daily_min:
        day_name = {0: "Monday", 1: "Tuesday", 2: "Wednesday", 3: "Thursday",
                    4: "Friday", 5: "Saturday", 6: "Sunday"}
        for sec in sections:
            label = f"{sec.class_.name} {sec.name}"
            for subj_id in core_ids:
                hours = sec_subject_hours.get((sec.id, subj_id), 0)
                subj_obj = next((s for s in subjects if s.id == subj_id), None)
                if not subj_obj:
                    continue
                needed = core_daily_min * len(days)
                if hours < needed:
                    raise TimetableGenerationError(
                        f"'{subj_obj.name}' must appear at least {core_daily_min} time(s) every "
                        f"day in section '{label}', which needs {needed} weekly periods, but only "
                        f"{hours} are configured. Increase its weekly hours to {needed}, or lower "
                        f"core_subject_daily_min."
                    )
                if hours > max_lessons_per_day * len(days):
                    continue  # already reported by the subject-spread lint

                allowed = sec_subject_teachers.get((sec.id, subj_id), [])
                if len(allowed) != 1:
                    continue
                t = teacher_by_id.get(allowed[0])
                if not t:
                    continue
                t_name = t.user.name if t.user else f"Teacher {allowed[0]}"
                blank_days = [
                    d for d in days
                    if not [
                        p for p in periods
                        if teacher_avail_map.get((allowed[0], d, p), True) is not False
                        and (sec.id, d, p) not in locked_by_slot
                    ]
                ]
                if blank_days:
                    listed = ", ".join(day_name.get(d, str(d)) for d in blank_days)
                    raise TimetableGenerationError(
                        f"'{subj_obj.name}' must appear every day in section '{label}', but its "
                        f"only teacher '{t_name}' has no availability on {listed}. Give "
                        f"'{t_name}' at least {core_daily_min} free period(s) on {listed}, "
                        f"allocate '{subj_obj.name}' in '{label}' to another teacher, or remove "
                        f"'{subj_obj.name}' from the daily-core requirement."
                    )

    # 2h. Lint the weekly class-teacher double period.
    if policies.get("class_teacher_double_period", False):
        if len(periods) < 2:
            raise TimetableGenerationError(
                "class_teacher_double_period requires at least 2 periods per day."
            )
        p_first, p_second = periods[0], periods[1]
        for sec in sections:
            label = f"{sec.class_.name} {sec.name}"
            ct_id = getattr(sec, "class_teacher_id", None)
            if not ct_id:
                raise TimetableGenerationError(
                    f"Section '{label}' has no class teacher, but class_teacher_double_period "
                    f"is enabled. Assign a class teacher, or disable the policy."
                )
            t = teacher_by_id.get(ct_id)
            t_name = t.user.name if t and t.user else f"Teacher {ct_id}"

            taught = [sid for (s_id, sid), tids in sec_subject_teachers.items()
                      if s_id == sec.id and ct_id in tids and sec_subject_hours.get((s_id, sid), 0) > 0]
            if not taught:
                raise TimetableGenerationError(
                    f"Class teacher '{t_name}' of section '{label}' teaches no subject there, so "
                    f"they cannot take periods {p_first} and {p_second}. Allocate them a subject "
                    f"in '{label}', or disable class_teacher_double_period."
                )

            ok_days = [
                d for d in days
                if all(
                    teacher_avail_map.get((ct_id, d, p), True) is not False
                    and (sec.id, d, p) not in locked_by_slot
                    for p in (p_first, p_second)
                )
            ]
            if not ok_days:
                raise TimetableGenerationError(
                    f"Class teacher '{t_name}' of section '{label}' is never free for both "
                    f"period {p_first} and period {p_second} on the same day, so the weekly "
                    f"class-teacher double period cannot be scheduled. Widen their availability "
                    f"or choose a different class teacher."
                )

    # 2i. Lint the continuous double-period policy. Each named subject must form N
    # back-to-back pairs per week; catch the obvious impossibilities with a clear message
    # rather than letting the solver return a bare "infeasible".
    from app.services.policy_engine import PolicyEngine as _PE
    dp_reqs = _PE.double_period_requirements(config, subjects)
    if dp_reqs:
        adj_pairs = _PE.adjacent_period_pairs(config, periods)
        if not adj_pairs:
            raise TimetableGenerationError(
                "Continuous double periods are required, but no two periods are back-to-back "
                "(every consecutive pair is separated by a break in period_timings). Remove the "
                "double-period requirement or adjust the period timings."
            )
        if not policies.get("double_periods_allowed", False):
            raise TimetableGenerationError(
                "Continuous double periods require a subject to appear twice on the same day, "
                "but 'double_periods_allowed' is off. Enable it in scheduling policies."
            )
        subj_by_id = {s.id: s for s in subjects}
        for subj_id, req in dp_reqs.items():
            s_name = subj_by_id[subj_id].name
            # A double needs at least 2 lessons; req doubles need at least 2*req weekly hours,
            # and each double occupies its own day (spread cap 2), so req <= number of days.
            if req > len(days):
                raise TimetableGenerationError(
                    f"'{s_name}' is required to have {req} double periods per week, but there "
                    f"are only {len(days)} teaching day(s) and a subject can hold at most one "
                    f"double per day. Reduce its double-period requirement to at most {len(days)}."
                )
            for sec in sections:
                hours = sec_subject_hours.get((sec.id, subj_id), 0)
                if hours <= 0:
                    continue
                if hours < 2 * req:
                    label = f"{sec.class_.name} {sec.name}"
                    raise TimetableGenerationError(
                        f"'{s_name}' needs {req} double period(s) ({2 * req} periods) in section "
                        f"'{label}', but only {hours} weekly hour(s) are configured there. Raise "
                        f"'{s_name}' to at least {2 * req} weekly hours, or lower its "
                        f"double-period requirement."
                    )

    # 2j. Lint the subject-forbidden-periods policy. Removing periods must not drop a
    # subject below the room it needs. Necessary condition: allowed periods x days,
    # capped at the per-day spread, must cover the weekly hours.
    forbidden_map = _PE.subject_forbidden_periods(config, subjects, activities)
    if forbidden_map:
        for (kind, obj_id), pers in forbidden_map.items():
            allowed_periods = [p for p in periods if p not in pers]
            if kind == "subj":
                s_name = next((s.name for s in subjects if s.id == obj_id), f"Subject {obj_id}")
                if not allowed_periods:
                    raise TimetableGenerationError(
                        f"'{s_name}' is forbidden in every period, so it can never be scheduled. "
                        f"Relax its forbidden-period list."
                    )
                per_day_cap = max_lessons_per_day  # respects double_periods_allowed
                capacity = min(len(allowed_periods), per_day_cap) * len(days)
                for sec in sections:
                    hours = sec_subject_hours.get((sec.id, obj_id), 0)
                    if hours > capacity:
                        label = f"{sec.class_.name} {sec.name}"
                        raise TimetableGenerationError(
                            f"'{s_name}' needs {hours} weekly period(s) in section '{label}', but "
                            f"after forbidding period(s) {sorted(pers)} only {len(allowed_periods)} "
                            f"period(s)/day remain, allowing at most {capacity} across {len(days)} "
                            f"day(s). Free up a period, reduce '{s_name}' hours, or shrink the "
                            f"forbidden list."
                        )
            else:
                a_name = next((a.name for a in activities if a.id == obj_id), f"Activity {obj_id}")
                a_hours = next((a.weekly_hours for a in activities if a.id == obj_id), 0)
                if not allowed_periods and a_hours > 0:
                    raise TimetableGenerationError(
                        f"Activity '{a_name}' is forbidden in every period but needs "
                        f"{a_hours} weekly period(s). Relax its forbidden-period list."
                    )

        # 2j-2. Teacher-slot capacity under the ban. When one teacher is the sole provider of
        # a forbidden subject across many sections (e.g. a single PE teacher for the whole
        # school), the ban can leave fewer open period-slots than the lessons they must give.
        # This is exactly the failure that otherwise surfaces as a bare "infeasible". Only the
        # single-eligible-teacher case is checked, so it is a necessary condition with no
        # false alarms.
        forced_ban_demand: dict[int, int] = {}
        ban_allowed_periods: dict[int, set] = {}
        ban_subjects: dict[int, set] = {}
        for (kind, obj_id), pers in forbidden_map.items():
            if kind != "subj":
                continue
            allowed_p = {p for p in periods if p not in pers}
            s_name = next((s.name for s in subjects if s.id == obj_id), f"Subject {obj_id}")
            for sec in sections:
                allowed_t = sec_subject_teachers.get((sec.id, obj_id), [])
                hours = sec_subject_hours.get((sec.id, obj_id), 0)
                if hours > 0 and len(allowed_t) == 1:
                    t_id = allowed_t[0]
                    forced_ban_demand[t_id] = forced_ban_demand.get(t_id, 0) + hours
                    ban_allowed_periods.setdefault(t_id, set()).update(allowed_p)
                    ban_subjects.setdefault(t_id, set()).add(s_name)
        for t_id, demand in forced_ban_demand.items():
            t = teacher_by_id.get(t_id)
            if not t:
                continue
            open_slots = sum(
                1 for d in days for p in ban_allowed_periods[t_id]
                if teacher_avail_map.get((t_id, d, p), True) is not False
                and (t_id, d, p) not in locked_teacher_slots
            )
            if demand > open_slots:
                t_name = t.user.name if t.user else f"Teacher {t_id}"
                subj_list = ", ".join(sorted(ban_subjects[t_id]))
                raise TimetableGenerationError(
                    f"Teacher '{t_name}' must teach {demand} period(s) of {subj_list}, but after "
                    f"the forbidden-period ban only {open_slots} open slot(s) remain in their "
                    f"allowed periods. Split {subj_list} across another teacher, relax the "
                    f"forbidden-period list, or free up the teacher's availability."
                )

    # 2k. Lint single-per-day subjects: a subject capped at one lesson/day cannot have more
    # weekly hours than there are teaching days.
    single_ids = _PE.single_per_day_subject_ids(config, subjects)
    if single_ids:
        for subj_id in single_ids:
            s_name = next((s.name for s in subjects if s.id == subj_id), f"Subject {subj_id}")
            for sec in sections:
                hours = sec_subject_hours.get((sec.id, subj_id), 0)
                if hours > len(days):
                    label = f"{sec.class_.name} {sec.name}"
                    raise TimetableGenerationError(
                        f"'{s_name}' needs {hours} weekly period(s) in section '{label}', but it is "
                        f"limited to one per day across {len(days)} teaching day(s). Reduce "
                        f"'{s_name}' to at most {len(days)} weekly hours, or drop it from "
                        f"single_per_day_subjects."
                    )

    model = cp_model.CpModel()

    def slot_is_free(section_id: int, d: int, p: int) -> bool:
        return (section_id, d, p) not in locked_by_slot

    # x[section, day, period, subject, teacher] and y[section, day, period, activity]
    x: dict[tuple, cp_model.IntVar] = {}
    y: dict[tuple, cp_model.IntVar] = {}

    resources_enabled = config.get("resources", {}).get("enabled", True)

    for sec in sections:
        for d in days:
            for p in periods:
                if not slot_is_free(sec.id, d, p):
                    continue
                    
                for subj in subjects:
                    key = (sec.id, subj.id)
                    if sec_subject_hours.get(key, 0) <= 0:
                        continue

                    for t_id in sec_subject_teachers.get(key, []):
                        if (t_id, d, p) in locked_teacher_slots:
                            continue
                        if teacher_avail_map.get((t_id, d, p), True) is False:
                            continue
                        if resources_enabled and subj.resource_id and (subj.resource_id, d, p) in locked_resource_slots:
                            continue
                        x[(sec.id, d, p, subj.id, t_id)] = model.NewBoolVar(
                            f"x_s{sec.id}_d{d}_p{p}_sub{subj.id}_t{t_id}"
                        )
                        
                for act in activities:
                    if resources_enabled and act.resource_id and (act.resource_id, d, p) in locked_resource_slots:
                        continue
                    y[(sec.id, d, p, act.id)] = model.NewBoolVar(f"y_s{sec.id}_d{d}_p{p}_act{act.id}")

    # at most one lesson/activity per free (section, day, period) slot
    for sec in sections:
        for d in days:
            for p in periods:
                if not slot_is_free(sec.id, d, p):
                    continue
                terms = [x[k] for k in x if k[0] == sec.id and k[1] == d and k[2] == p]
                terms += [y[k] for k in y if k[0] == sec.id and k[1] == d and k[2] == p]
                if terms:
                    model.Add(sum(terms) <= 1)

    # subject weekly hours exact (accounting for hours already fixed by locked rows)
    for sec in sections:
        for subj in subjects:
            already = locked_subject_hours.get((sec.id, subj.id), 0)
            target = sec_subject_hours.get((sec.id, subj.id), 0) - already
            terms = [x[k] for k in x if k[0] == sec.id and k[3] == subj.id]
            if target < 0:
                raise TimetableGenerationError(
                    f"Locked slots already assign more than {sec_subject_hours.get((sec.id, subj.id), 0)} weekly hours of "
                    f"'{subj.name}' to a section - unlock some slots and regenerate."
                )
            model.Add(sum(terms) == target)

    # activity weekly hours exact
    for sec in sections:
        for act in activities:
            already = locked_activity_hours.get((sec.id, act.id), 0)
            target = act.weekly_hours - already
            terms = [y[k] for k in y if k[0] == sec.id and k[3] == act.id]
            if target < 0:
                raise TimetableGenerationError(
                    f"Locked slots already assign more than {act.weekly_hours} weekly hours of "
                    f"'{act.name}' to a section - unlock some slots and regenerate."
                )
            model.Add(sum(terms) == target)

    # teacher: no double booking at the same (day, period) across all sections
    for t in teachers:
        for d in days:
            for p in periods:
                terms = [x[k] for k in x if k[1] == d and k[2] == p and k[4] == t.id]
                if terms:
                    model.Add(sum(terms) <= 1)

    # teacher: weekly hour cap (including hours already used by locked rows)
    for t in teachers:
        terms = [x[k] for k in x if k[4] == t.id]
        if terms:
            cap = t.max_weekly_hours - locked_teacher_hours.get(t.id, 0)
            model.Add(sum(terms) <= max(cap, 0))

    # resource conflicts: at most one subject/activity using a given resource per (day, period)
    if resources_enabled:
        resource_users: dict[int, list] = {}
        for subj in subjects:
            if subj.resource_id:
                resource_users.setdefault(subj.resource_id, []).append(("subj", subj.id))
        for act in activities:
            if act.resource_id:
                resource_users.setdefault(act.resource_id, []).append(("act", act.id))

        for res_id in resource_users:
            for d in days:
                for p in periods:
                    terms = [x[k] for k in x if k[1] == d and k[2] == p and ("subj", k[3]) in resource_users[res_id]]
                    terms += [y[k] for k in y if k[1] == d and k[2] == p and ("act", k[3]) in resource_users[res_id]]
                    if terms:
                        model.Add(sum(terms) <= 1)

    # Teacher Preferences: Hard constraints (e.g. max_daily)
    for pref in preferences:
        if pref.preference_type == "max_daily" and pref.value is not None:
            for d in days:
                terms = [x[k] for k in x if k[1] == d and k[4] == pref.teacher_id]
                if terms:
                    model.Add(sum(terms) <= pref.value)

    # Teacher Preferences: Soft constraints (objective terms)
    objective_terms = []
    for pref in preferences:
        if pref.preference_type == "preferred_period" and pref.day_of_week is not None and pref.period is not None:
            terms = [x[k] for k in x if k[1] == pref.day_of_week and k[2] == pref.period and k[4] == pref.teacher_id]
            objective_terms.extend([t_var * pref.weight for t_var in terms])
        elif pref.preference_type == "avoid_period" and pref.day_of_week is not None and pref.period is not None:
            terms = [x[k] for k in x if k[1] == pref.day_of_week and k[2] == pref.period and k[4] == pref.teacher_id]
            objective_terms.extend([t_var * (-pref.weight) for t_var in terms])
        elif pref.preference_type == "preferred_day" and pref.day_of_week is not None:
            terms = [x[k] for k in x if k[1] == pref.day_of_week and k[4] == pref.teacher_id]
            objective_terms.extend([t_var * pref.weight for t_var in terms])
        elif pref.preference_type == "avoid_day" and pref.day_of_week is not None:
            terms = [x[k] for k in x if k[1] == pref.day_of_week and k[4] == pref.teacher_id]
            objective_terms.extend([t_var * (-pref.weight) for t_var in terms])

    # Apply scheduling policies dynamically
    from app.services.policy_engine import PolicyEngine
    # Locked rows already consume part of a day's core allowance.
    locked_core_by_sec_day: dict[tuple[int, int], int] = {}
    locked_subject_by_sec_day: dict[tuple[int, int, int], int] = {}
    for r in locked_rows:
        if r.subject_id:
            k3 = (r.section_id, r.day_of_week, r.subject_id)
            locked_subject_by_sec_day[k3] = locked_subject_by_sec_day.get(k3, 0) + 1
        if r.subject_id in core_ids:
            key = (r.section_id, r.day_of_week)
            locked_core_by_sec_day[key] = locked_core_by_sec_day.get(key, 0) + 1

    policy_objective_terms = PolicyEngine.apply_policies(
        model, x, y, config, days, periods, sections, subjects, activities, teachers,
        resources_enabled, locked_core_by_sec_day=locked_core_by_sec_day,
        locked_subject_by_sec_day=locked_subject_by_sec_day,
    )
    if policy_objective_terms:
        objective_terms.extend(policy_objective_terms)

    if objective_terms:
        model.Maximize(sum(objective_terms))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit_seconds
    solver.parameters.num_search_workers = 8
    status = solver.Solve(model)

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        raise TimetableGenerationError(
            "No feasible timetable exists for the current data. This usually means there aren't "
            "enough qualified teachers, teacher weekly-hour caps are too low, or a shared resource "
            "is over-requested. Try adding teachers, raising max_weekly_hours, or reducing weekly_hours."
        )

    slots: list[GeneratedSlot] = []
    for (sec_id, d, p, subj_id, t_id), var in x.items():
        if solver.Value(var):
            subj = next(s for s in subjects if s.id == subj_id)
            slots.append(GeneratedSlot(
                section_id=sec_id, day_of_week=d, period=p,
                subject_id=subj_id, teacher_id=t_id, resource_id=subj.resource_id,
            ))
    for (sec_id, d, p, act_id), var in y.items():
        if solver.Value(var):
            act = next(a for a in activities if a.id == act_id)
            slots.append(GeneratedSlot(
                section_id=sec_id, day_of_week=d, period=p,
                activity_id=act_id, resource_id=act.resource_id,
            ))

    return GenerationResult(
        slots=slots,
        sections_scheduled=len(sections),
        optimal=(status == cp_model.OPTIMAL),
    )

