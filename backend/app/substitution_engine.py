"""
Auto Substitute Engine (Leave Management, Phase 4).

Given an approved leave for a teacher (possibly spanning several days), this
finds a substitute for every master-timetable slot that teacher would have
taught on each affected date, and returns the result as a plan of
SubstituteMatch objects. The router (app/routers/leaves.py) is responsible
for turning matches into Substitution rows - this module never writes to the
database, it only reads and decides. The master Timetable is never modified
(Layer 2 overlay, per spec); see GET /substitutions/schedule for the
resulting effective schedule on a given date.

Priority order per spec, applied per slot. A candidate is only eligible when they are
BOTH available (inside their configured availability) and free (not already teaching
or substituting at that day/period) — hard constraints are never broken to fill a slot.

  1. Same-subject teacher, free + available                     -> "same_subject"
  2. Any free + available teacher, ties broken by lowest
     workload, then by sharing the absent teacher's department  -> "available"
  3. Nobody is both free and available: the slot is left
     "uncovered" for manual admin assignment via
     POST /substitutions.                                       -> "uncovered"
"""
from dataclasses import dataclass
from datetime import date as date_cls

from sqlalchemy.orm import Session, joinedload

from app import models


@dataclass
class SubstituteMatch:
    timetable_id: int
    date: date_cls
    substitute_teacher_id: int | None
    reason: str
    method: str  # "same_subject" | "available" | "uncovered"


def leave_date_range(leave: models.Leave) -> list[date_cls]:
    start = leave.date
    end = leave.end_date or leave.date
    if end < start:
        end = start
    days = (end - start).days
    return [start + __import__("datetime").timedelta(days=i) for i in range(days + 1)]


def _teacher_workload(db: Session, teacher_id: int) -> int:
    """Proxy for current workload: number of periods/week already on the
    master timetable for this teacher. Lower = less loaded."""
    return db.query(models.Timetable).filter(models.Timetable.teacher_id == teacher_id).count()


def _is_on_approved_leave(db: Session, teacher_id: int, on_date: date_cls) -> bool:
    leaves = db.query(models.Leave).filter(
        models.Leave.teacher_id == teacher_id,
        models.Leave.status == models.LeaveStatus.approved,
    ).all()
    for lv in leaves:
        start = lv.date
        end = lv.end_date or lv.date
        if start <= on_date <= end:
            return True
    return False


def _is_available(db: Session, teacher_id: int, day_of_week: int, period: int) -> bool:
    """A teacher may never be scheduled outside their configured availability —
    those periods belong to Higher Secondary classes. Absent row = available."""
    row = (
        db.query(models.TeacherAvailability)
        .filter(
            models.TeacherAvailability.teacher_id == teacher_id,
            models.TeacherAvailability.day_of_week == day_of_week,
            models.TeacherAvailability.period == period,
        )
        .first()
    )
    return True if row is None else bool(row.is_available)


def _is_free(db: Session, teacher_id: int, day_of_week: int, period: int, on_date: date_cls) -> bool:
    """Free = available at this day/period, not teaching another section on the master
    timetable then, and not already covering another substitution at this exact
    day/period on this date."""
    if not _is_available(db, teacher_id, day_of_week, period):
        return False
    busy_master = db.query(models.Timetable).filter(
        models.Timetable.teacher_id == teacher_id,
        models.Timetable.day_of_week == day_of_week,
        models.Timetable.period == period,
    ).first()
    if busy_master:
        return False
    busy_sub = (
        db.query(models.Substitution)
        .join(models.Timetable, models.Substitution.timetable_id == models.Timetable.id)
        .filter(
            models.Substitution.substitute_teacher_id == teacher_id,
            models.Substitution.date == on_date,
            models.Timetable.day_of_week == day_of_week,
            models.Timetable.period == period,
        )
        .first()
    )
    return busy_sub is None


def find_substitute(db: Session, slot: models.Timetable, on_date: date_cls, leave_teacher_id: int) -> SubstituteMatch:
    """Find the best substitute for one master-timetable slot on one date.
    Call db.flush() after acting on the result (before the next call) so
    subsequent `_is_free`/workload checks see the just-made assignment."""
    school_id = slot.school_id
    day_of_week = slot.day_of_week
    period = slot.period

    candidates = (
        db.query(models.Teacher)
        .options(joinedload(models.Teacher.user), joinedload(models.Teacher.subjects))
        .filter(models.Teacher.school_id == school_id, models.Teacher.id != leave_teacher_id)
        .all()
    )
    candidates = [c for c in candidates if c.user.is_active]
    candidates = [c for c in candidates if not _is_on_approved_leave(db, c.id, on_date)]

    if not candidates:
        return SubstituteMatch(slot.id, on_date, None, "No other active teachers at this school.", "uncovered")

    free_candidates = [c for c in candidates if _is_free(db, c.id, day_of_week, period, on_date)]

    # Tier 1: same-subject + free
    if slot.subject_id:
        tier1 = [c for c in free_candidates if any(s.id == slot.subject_id for s in c.subjects)]
        if tier1:
            best = min(tier1, key=lambda c: _teacher_workload(db, c.id))
            wl = _teacher_workload(db, best.id)
            return SubstituteMatch(
                slot.id, on_date, best.id,
                f"Same-subject teacher, available at this period, lowest workload ({wl} periods/week).",
                "same_subject",
            )

    # Tier 2: any free + available teacher. Ties broken by lowest workload, then by
    # sharing the absent teacher's department.
    leave_teacher = db.query(models.Teacher).filter(models.Teacher.id == leave_teacher_id).first()
    dept = leave_teacher.department if leave_teacher else None
    if free_candidates:
        best = min(
            free_candidates,
            key=lambda c: (_teacher_workload(db, c.id), 0 if dept and c.department == dept else 1),
        )
        wl = _teacher_workload(db, best.id)
        same_dept = " same department," if dept and best.department == dept else ""
        return SubstituteMatch(
            slot.id, on_date, best.id,
            f"Available teacher (different subject),{same_dept} lowest workload ({wl} periods/week).",
            "available",
        )

    # Nobody is both free and available. Hard constraints (teacher clash, availability)
    # are never broken to fill a slot — the period is left for manual assignment.
    return SubstituteMatch(
        slot.id, on_date, None,
        "No teacher is both free and available at this period. Covering it would double-book "
        "someone or use a teacher outside their availability, so it is left for manual "
        "assignment.",
        "uncovered",
    )


def slots_for_teacher_on_weekday(db: Session, teacher_id: int, day_of_week: int) -> list[models.Timetable]:
    return (
        db.query(models.Timetable)
        .options(
            joinedload(models.Timetable.section).joinedload(models.Section.class_),
            joinedload(models.Timetable.subject),
            joinedload(models.Timetable.activity),
        )
        .filter(models.Timetable.teacher_id == teacher_id, models.Timetable.day_of_week == day_of_week)
        .all()
    )
