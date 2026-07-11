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

from sqlalchemy import func
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


def on_duty_date_range(od: "models.OnDuty") -> list[date_cls]:
    start = od.date
    end = od.end_date or od.date
    if end < start:
        end = start
    days = (end - start).days
    return [start + __import__("datetime").timedelta(days=i) for i in range(days + 1)]


def _od_covers_period(od: "models.OnDuty", period: int) -> bool:
    """No period bounds set = the duty occupies the whole day."""
    if od.start_period is None and od.end_period is None:
        return True
    lo = od.start_period if od.start_period is not None else period
    hi = od.end_period if od.end_period is not None else period
    return lo <= period <= hi


def _is_on_approved_on_duty(db: Session, teacher_id: int, on_date: date_cls, period: int) -> bool:
    """A teacher on approved on-duty is physically present but unavailable to teach
    the periods their duty covers - so they must never be picked as a substitute for
    those periods (they may still cover periods outside the duty window)."""
    rows = db.query(models.OnDuty).filter(
        models.OnDuty.teacher_id == teacher_id,
        models.OnDuty.status == models.OnDutyStatus.approved,
    ).all()
    for od in rows:
        start = od.date
        end = od.end_date or od.date
        if start <= on_date <= end and _od_covers_period(od, period):
            return True
    return False


def slots_for_on_duty(db: Session, od: "models.OnDuty", on_date: date_cls) -> list[models.Timetable]:
    """The master-timetable slots this on-duty actually takes the teacher away from."""
    day_of_week = on_date.weekday()
    slots = slots_for_teacher_on_weekday(db, od.teacher_id, day_of_week)
    return [s for s in slots if _od_covers_period(od, s.period)]


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
    # Present-but-occupied (exam duty, office work, ...) blocks cover for that period.
    if _is_on_approved_on_duty(db, teacher_id, on_date, period):
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


@dataclass
class RankedCandidate:
    teacher_id: int
    teacher_name: str
    rank: int
    score: int          # 0-100 suitability
    method: str         # same_subject | available
    reason: str


def rank_substitutes(
    db: Session,
    slot: models.Timetable,
    on_date: date_cls,
    absent_teacher_id: int,
    exclude_teacher_ids: set[int] | None = None,
) -> list[RankedCandidate]:
    """Score and rank EVERY eligible teacher for this slot - not just the best one.

    Rank 1 is auto-assigned by the caller; the rest are stored as backups so that a
    decline can be promoted instantly without re-solving. Hard constraints are never
    traded away for a higher score: a teacher who is on leave, on duty, outside their
    availability, already teaching, or already covering another class at this period
    simply is not a candidate at all.

    Score (0-100): starts from suitability of the subject match, then rewards a lighter
    existing workload and the same department. It is a ranking aid, not a licence to
    break a constraint.
    """
    exclude = exclude_teacher_ids or set()
    school_id = slot.school_id
    day_of_week = slot.day_of_week
    period = slot.period

    candidates = (
        db.query(models.Teacher)
        .options(joinedload(models.Teacher.user), joinedload(models.Teacher.subjects))
        .filter(models.Teacher.school_id == school_id, models.Teacher.id != absent_teacher_id)
        .all()
    )
    candidates = [c for c in candidates if c.user and c.user.is_active and c.id not in exclude]
    if not candidates:
        return []

    on_leave = {
        lv.teacher_id for lv in db.query(models.Leave).filter(
            models.Leave.school_id == school_id,
            models.Leave.status == models.LeaveStatus.approved,
            models.Leave.date <= on_date,
        ) if lv.date <= on_date <= (lv.end_date or lv.date)
    }
    on_duty_ids = {
        od.teacher_id for od in db.query(models.OnDuty).filter(
            models.OnDuty.school_id == school_id,
            models.OnDuty.status == models.OnDutyStatus.approved,
            models.OnDuty.date <= on_date,
        )
        if od.date <= on_date <= (od.end_date or od.date) and _od_covers_period(od, period)
    }
    blocked_avail = {
        a.teacher_id for a in db.query(models.TeacherAvailability).filter(
            models.TeacherAvailability.day_of_week == day_of_week,
            models.TeacherAvailability.period == period,
            models.TeacherAvailability.is_available.is_(False),
        )
    }
    busy_master = {
        t.teacher_id for t in db.query(models.Timetable).filter(
            models.Timetable.school_id == school_id,
            models.Timetable.day_of_week == day_of_week,
            models.Timetable.period == period,
            models.Timetable.teacher_id.isnot(None),
        )
    }
    busy_sub = {
        s.substitute_teacher_id for s in db.query(models.Substitution)
        .join(models.Timetable, models.Substitution.timetable_id == models.Timetable.id)
        .filter(
            models.Substitution.date == on_date,
            models.Timetable.day_of_week == day_of_week,
            models.Timetable.period == period,
        )
    }
    workload = dict(
        db.query(models.Timetable.teacher_id, func.count(models.Timetable.id))
        .filter(models.Timetable.school_id == school_id,
                models.Timetable.teacher_id.isnot(None))
        .group_by(models.Timetable.teacher_id)
        .all()
    )
    absent = db.query(models.Teacher).filter(models.Teacher.id == absent_teacher_id).first()
    dept = absent.department if absent else None

    free = [
        c for c in candidates
        if c.id not in on_leave
        and c.id not in blocked_avail
        and c.id not in on_duty_ids
        and c.id not in busy_master
        and c.id not in busy_sub
    ]
    if not free:
        return []

    max_wl = max((workload.get(c.id, 0) for c in free), default=0) or 1

    scored: list[tuple[int, RankedCandidate]] = []
    for c in free:
        wl = workload.get(c.id, 0)
        teaches_subject = bool(slot.subject_id) and any(s.id == slot.subject_id for s in c.subjects)
        same_dept = bool(dept) and c.department == dept

        base = 70 if teaches_subject else 40          # subject match dominates
        base += 12 if same_dept else 0
        base += round(18 * (1 - wl / max_wl))         # lighter load ranks higher
        score = max(1, min(100, base))

        bits = []
        if teaches_subject:
            bits.append("teaches this subject")
        if same_dept:
            bits.append("same department")
        bits.append(f"current load {wl} periods/week")
        scored.append((score, RankedCandidate(
            teacher_id=c.id,
            teacher_name=c.user.name if c.user else f"Teacher {c.id}",
            rank=0,
            score=score,
            method="same_subject" if teaches_subject else "available",
            reason=", ".join(bits).capitalize() + ".",
        )))

    scored.sort(key=lambda t: (-t[0], t[1].teacher_name))
    out: list[RankedCandidate] = []
    for i, (_, rc) in enumerate(scored, start=1):
        rc.rank = i
        out.append(rc)
    return out


def find_substitute(db: Session, slot: models.Timetable, on_date: date_cls, leave_teacher_id: int) -> SubstituteMatch:
    """Find the best substitute for one master-timetable slot on one date.
    Call db.flush() after acting on the result (before the next call) so
    subsequent free/workload checks see the just-made assignment.

    Eligibility is identical to the per-teacher helpers above, but every fact is
    fetched in ONE batch query instead of one-per-candidate: the naive form issued
    ~150 round-trips per slot, which is minutes of latency against a remote DB.
    """
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
    if not candidates:
        return SubstituteMatch(slot.id, on_date, None, "No other active teachers at this school.", "uncovered")

    # ---- batch-load every eligibility fact for this (date, day, period) ----
    on_leave = {
        lv.teacher_id for lv in db.query(models.Leave).filter(
            models.Leave.school_id == school_id,
            models.Leave.status == models.LeaveStatus.approved,
            models.Leave.date <= on_date,
        ) if lv.date <= on_date <= (lv.end_date or lv.date)
    }
    on_duty_ids = {
        od.teacher_id for od in db.query(models.OnDuty).filter(
            models.OnDuty.school_id == school_id,
            models.OnDuty.status == models.OnDutyStatus.approved,
            models.OnDuty.date <= on_date,
        )
        if od.date <= on_date <= (od.end_date or od.date) and _od_covers_period(od, period)
    }
    blocked_avail = {
        a.teacher_id for a in db.query(models.TeacherAvailability).filter(
            models.TeacherAvailability.day_of_week == day_of_week,
            models.TeacherAvailability.period == period,
            models.TeacherAvailability.is_available.is_(False),
        )
    }
    busy_master = {
        t.teacher_id for t in db.query(models.Timetable).filter(
            models.Timetable.school_id == school_id,
            models.Timetable.day_of_week == day_of_week,
            models.Timetable.period == period,
            models.Timetable.teacher_id.isnot(None),
        )
    }
    busy_sub = {
        s.substitute_teacher_id for s in db.query(models.Substitution)
        .join(models.Timetable, models.Substitution.timetable_id == models.Timetable.id)
        .filter(
            models.Substitution.date == on_date,
            models.Timetable.day_of_week == day_of_week,
            models.Timetable.period == period,
        )
    }
    workload = dict(
        db.query(models.Timetable.teacher_id, func.count(models.Timetable.id))
        .filter(models.Timetable.school_id == school_id,
                models.Timetable.teacher_id.isnot(None))
        .group_by(models.Timetable.teacher_id)
        .all()
    )

    candidates = [c for c in candidates if c.id not in on_leave]
    if not candidates:
        return SubstituteMatch(slot.id, on_date, None, "No other active teachers at this school.", "uncovered")

    def _wl(tid: int) -> int:
        return workload.get(tid, 0)

    free_candidates = [
        c for c in candidates
        if c.id not in blocked_avail          # outside their configured availability
        and c.id not in on_duty_ids           # present but occupied (exam duty, office, ...)
        and c.id not in busy_master           # already teaching another section then
        and c.id not in busy_sub              # already covering another substitution then
    ]

    # Tier 1: same-subject + free
    if slot.subject_id:
        tier1 = [c for c in free_candidates if any(s.id == slot.subject_id for s in c.subjects)]
        if tier1:
            best = min(tier1, key=lambda c: _wl(c.id))
            return SubstituteMatch(
                slot.id, on_date, best.id,
                f"Same-subject teacher, available at this period, lowest workload ({_wl(best.id)} periods/week).",
                "same_subject",
            )

    # Tier 2: any free + available teacher. Ties broken by lowest workload, then by
    # sharing the absent teacher's department.
    leave_teacher = db.query(models.Teacher).filter(models.Teacher.id == leave_teacher_id).first()
    dept = leave_teacher.department if leave_teacher else None
    if free_candidates:
        best = min(
            free_candidates,
            key=lambda c: (_wl(c.id), 0 if dept and c.department == dept else 1),
        )
        same_dept = " same department," if dept and best.department == dept else ""
        return SubstituteMatch(
            slot.id, on_date, best.id,
            f"Available teacher (different subject),{same_dept} lowest workload ({_wl(best.id)} periods/week).",
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
