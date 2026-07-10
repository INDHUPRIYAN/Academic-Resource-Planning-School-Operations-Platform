"""Rule 21 - Final Verification.

An INDEPENDENT checker. It never looks at the CP-SAT model; it re-derives every hard
constraint from the rows that are about to be written plus the school's configuration.
If anything fails the timetable is rejected rather than committed.

This is deliberately duplicated logic: a solver bug that silently drops a constraint
would still be caught here.
"""
from __future__ import annotations

import collections
import json
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app import models
from app.services.policy_engine import PolicyEngine


@dataclass
class Slot:
    section_id: int
    day_of_week: int
    period: int
    subject_id: int | None = None
    activity_id: int | None = None
    teacher_id: int | None = None
    resource_id: int | None = None


@dataclass
class VerificationReport:
    violations: list[dict] = field(default_factory=list)
    checks: dict[str, bool] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return not self.violations

    def fail(self, rule: str, detail: str, **ctx):
        self.checks[rule] = False
        self.violations.append({"rule": rule, "detail": detail, **ctx})

    def ok(self, rule: str):
        self.checks.setdefault(rule, True)

    def as_dict(self) -> dict:
        return {
            "passed": self.passed,
            "checks": self.checks,
            "violations": self.violations,
        }


def verify(db: Session, school_id: int, slots: list[Slot]) -> VerificationReport:
    r = VerificationReport()

    school = db.query(models.School).filter(models.School.id == school_id).first()
    if not school:
        r.fail("school", "School not found")
        return r

    cfg_row = db.query(models.SchoolConfig).filter(models.SchoolConfig.school_id == school_id).first()
    config = {}
    if cfg_row:
        try:
            config = json.loads(cfg_row.config)
        except (ValueError, TypeError):
            config = {}
    policies = config.get("scheduling_policies", {})

    subjects = db.query(models.Subject).filter(models.Subject.school_id == school_id).all()
    activities = db.query(models.Activity).filter(models.Activity.school_id == school_id).all()
    teachers = db.query(models.Teacher).filter(models.Teacher.school_id == school_id).all()
    classes = db.query(models.Class).filter(models.Class.school_id == school_id).all()
    sections = (
        db.query(models.Section)
        .filter(models.Section.class_id.in_([c.id for c in classes] or [-1]))
        .all()
    )
    subj = {s.id: s for s in subjects}
    act = {a.id: a for a in activities}
    tname = {t.id: (t.user.name if t.user else f"Teacher {t.id}") for t in teachers}
    sname = {s.id: f"{s.class_.name} {s.name}" for s in sections}

    days = list(range(school.working_days))
    periods = list(range(1, school.periods_per_day + 1))

    # ---- Rule 5: class clash -------------------------------------------------
    per_slot = collections.Counter((s.section_id, s.day_of_week, s.period) for s in slots)
    for (sec, d, p), n in per_slot.items():
        if n > 1:
            r.fail("class_clash", f"Section '{sname.get(sec, sec)}' has {n} entries on day {d} period {p}",
                   section=sname.get(sec), day=d, period=p)
    r.ok("class_clash")

    # ---- Rule 4: teacher clash ----------------------------------------------
    per_teacher = collections.Counter(
        (s.teacher_id, s.day_of_week, s.period) for s in slots if s.teacher_id
    )
    for (t, d, p), n in per_teacher.items():
        if n > 1:
            r.fail("teacher_clash", f"Teacher '{tname.get(t, t)}' is in {n} classes on day {d} period {p}",
                   teacher=tname.get(t), day=d, period=p)
    r.ok("teacher_clash")

    # ---- Rule 3: teacher availability ---------------------------------------
    avail = {
        (a.teacher_id, a.day_of_week, a.period): a.is_available
        for a in db.query(models.TeacherAvailability).filter(
            models.TeacherAvailability.teacher_id.in_([t.id for t in teachers] or [-1])
        )
    }
    for s in slots:
        if s.teacher_id and avail.get((s.teacher_id, s.day_of_week, s.period), True) is False:
            r.fail("teacher_availability",
                   f"Teacher '{tname.get(s.teacher_id)}' scheduled on day {s.day_of_week} "
                   f"period {s.period}, outside their availability",
                   teacher=tname.get(s.teacher_id), day=s.day_of_week, period=s.period)
    r.ok("teacher_availability")

    # ---- Rule 6: resource clash ---------------------------------------------
    per_res = collections.Counter((s.resource_id, s.day_of_week, s.period) for s in slots if s.resource_id)
    for (res, d, p), n in per_res.items():
        if n > 1:
            r.fail("resource_clash", f"Resource {res} double-booked on day {d} period {p}",
                   resource_id=res, day=d, period=p)
    r.ok("resource_clash")

    # ---- Rule 2 & 10: weekly subject / activity hours exact ------------------
    subj_hours = collections.Counter((s.section_id, s.subject_id) for s in slots if s.subject_id)
    act_hours = collections.Counter((s.section_id, s.activity_id) for s in slots if s.activity_id)
    for sec in sections:
        for sj in subjects:
            want = sj.weekly_hours or 0
            got = subj_hours.get((sec.id, sj.id), 0)
            if want and got != want:
                r.fail("weekly_hours",
                       f"'{sj.name}' in '{sname[sec.id]}' has {got} periods, expected {want}",
                       section=sname[sec.id], subject=sj.name, got=got, expected=want)
        for a in activities:
            want = a.weekly_hours or 0
            got = act_hours.get((sec.id, a.id), 0)
            if want and got != want:
                r.fail("activity_hours",
                       f"Activity '{a.name}' in '{sname[sec.id]}' has {got} periods, expected {want}",
                       section=sname[sec.id], activity=a.name, got=got, expected=want)
    r.ok("weekly_hours")
    r.ok("activity_hours")

    # ---- Rule 1: fixed teacher assignments ----------------------------------
    method = config.get("teacher_assignment_method", "automatic")
    if method in ("manual", "hybrid"):
        allocated = {
            (a.section_id, a.subject_id): a.teacher_id
            for a in db.query(models.SubjectAssignment).filter(
                models.SubjectAssignment.school_id == school_id
            )
            if a.teacher_id
        }
        for s in slots:
            if s.subject_id and s.teacher_id:
                want = allocated.get((s.section_id, s.subject_id))
                if want and want != s.teacher_id:
                    r.fail("fixed_assignments",
                           f"'{subj[s.subject_id].name}' in '{sname.get(s.section_id)}' is taught by "
                           f"'{tname.get(s.teacher_id)}' but is allocated to '{tname.get(want)}'",
                           section=sname.get(s.section_id), subject=subj[s.subject_id].name)
    r.ok("fixed_assignments")

    # ---- Rule 9: fixed events preserved -------------------------------------
    locked = db.query(models.Timetable).filter(
        models.Timetable.school_id == school_id, models.Timetable.is_locked.is_(True)
    ).all()
    placed = {(s.section_id, s.day_of_week, s.period): s for s in slots}
    for lk in locked:
        got = placed.get((lk.section_id, lk.day_of_week, lk.period))
        if not got or got.activity_id != lk.activity_id or got.subject_id != lk.subject_id:
            r.fail("fixed_events",
                   f"Locked slot for '{sname.get(lk.section_id)}' on day {lk.day_of_week} "
                   f"period {lk.period} was not preserved",
                   section=sname.get(lk.section_id), day=lk.day_of_week, period=lk.period)
    r.ok("fixed_events")

    # ---- Rule 12: teacher workload ------------------------------------------
    weekly = collections.Counter(s.teacher_id for s in slots if s.teacher_id)
    for t in teachers:
        if weekly.get(t.id, 0) > (t.max_weekly_hours or 0):
            r.fail("teacher_workload",
                   f"Teacher '{tname[t.id]}' has {weekly[t.id]} periods, above their "
                   f"maximum of {t.max_weekly_hours}",
                   teacher=tname[t.id], got=weekly[t.id], maximum=t.max_weekly_hours)
    max_daily = policies.get("max_daily_periods")
    if max_daily:
        daily = collections.Counter((s.teacher_id, s.day_of_week) for s in slots if s.teacher_id)
        for (t, d), n in daily.items():
            if n > max_daily:
                r.fail("teacher_workload",
                       f"Teacher '{tname.get(t)}' has {n} periods on day {d}, above the daily "
                       f"maximum of {max_daily}", teacher=tname.get(t), day=d)
    r.ok("teacher_workload")

    # ---- Rule 11 & 13: subject spread ---------------------------------------
    max_per_day = 2 if policies.get("double_periods_allowed", False) else 1
    spread = collections.Counter(
        (s.section_id, s.subject_id, s.day_of_week) for s in slots if s.subject_id
    )
    for (sec, sj, d), n in spread.items():
        if n > max_per_day:
            r.fail("subject_spread",
                   f"'{subj[sj].name}' appears {n} times in '{sname.get(sec)}' on day {d}, "
                   f"above the limit of {max_per_day}",
                   section=sname.get(sec), subject=subj[sj].name, day=d)
    r.ok("subject_spread")

    # ---- Rule 7: daily core subjects ----------------------------------------
    core_ids = PolicyEngine.core_subject_ids(config, subjects)
    core_daily_min = policies.get("core_subject_daily_min")
    if core_ids and core_daily_min:
        counts = collections.Counter(
            (s.section_id, s.day_of_week, s.subject_id) for s in slots if s.subject_id
        )
        for sec in sections:
            for d in days:
                for cid in core_ids:
                    if counts.get((sec.id, d, cid), 0) < core_daily_min:
                        r.fail("daily_core_subjects",
                               f"'{subj[cid].name}' missing on day {d} in '{sname[sec.id]}'",
                               section=sname[sec.id], subject=subj[cid].name, day=d)
    r.ok("daily_core_subjects")

    # ---- Rule 8: weekly class-teacher double period -------------------------
    if policies.get("class_teacher_double_period", False) and len(periods) >= 2:
        p1, p2 = periods[0], periods[1]
        by_slot = {(s.section_id, s.day_of_week, s.period): s.teacher_id for s in slots}
        for sec in sections:
            ct = sec.class_teacher_id
            if not ct:
                r.fail("class_teacher_double_period",
                       f"Section '{sname[sec.id]}' has no class teacher", section=sname[sec.id])
                continue
            found = any(
                by_slot.get((sec.id, d, p1)) == ct and by_slot.get((sec.id, d, p2)) == ct
                for d in days
            )
            if not found:
                r.fail("class_teacher_double_period",
                       f"Class teacher '{tname.get(ct)}' of '{sname[sec.id]}' does not hold "
                       f"periods {p1} and {p2} on any single day",
                       section=sname[sec.id], teacher=tname.get(ct))
    r.ok("class_teacher_double_period")

    # ---- Rule 18: completeness ----------------------------------------------
    expected_total = len(days) * len(periods)
    per_section = collections.Counter(s.section_id for s in slots)
    demand = {}
    for sec in sections:
        want = sum(sj.weekly_hours or 0 for sj in subjects) + sum(a.weekly_hours or 0 for a in activities)
        demand[sec.id] = want
        got = per_section.get(sec.id, 0)
        if got != want:
            r.fail("completeness",
                   f"Section '{sname[sec.id]}' has {got} periods, expected {want}",
                   section=sname[sec.id], got=got, expected=want)
        if want > expected_total:
            r.fail("completeness",
                   f"Section '{sname[sec.id]}' demands {want} periods but the grid has "
                   f"only {expected_total}", section=sname[sec.id])
    r.ok("completeness")

    # ---- grid bounds ---------------------------------------------------------
    for s in slots:
        if s.day_of_week not in days or s.period not in periods:
            r.fail("grid_bounds",
                   f"Slot outside the grid: day {s.day_of_week} period {s.period}")
    r.ok("grid_bounds")

    return r
