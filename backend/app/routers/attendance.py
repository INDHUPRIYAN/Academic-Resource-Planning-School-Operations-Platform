"""Teacher Attendance Calendar (derived, read-only).

Deliberately NOT a stored table. Each day's status is computed on read from the
approved Leave / On-Duty records, which means:

  * it always auto-updates the moment a leave or on-duty is approved / rejected /
    cancelled - it can never drift out of sync, and
  * there is no write endpoint at all, so a teacher can never edit their own
    attendance. The only way to change it is through a leave or on-duty request
    that a principal (or vice-principal) approves.

Colours:  green = present, red = leave, yellow = on duty, grey = holiday/non-working.
"""
import calendar as calendar_mod
from datetime import date as date_cls, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload

from app import models, schemas
from app.auth import get_current_user, ADMIN_ROLES
from app.database import get_db
from app.substitution_engine import _od_covers_period, slots_for_teacher_on_weekday

router = APIRouter(prefix="/attendance", tags=["attendance"])

COLOURS = {"present": "green", "leave": "red", "on_duty": "yellow",
           "holiday": "grey", "non_working": "grey"}


def _resolve_teacher(db: Session, user: models.User, teacher_id: int | None) -> models.Teacher:
    """Teachers may only read their own calendar; admins/principals may read anyone's."""
    if user.role == models.RoleEnum.teacher:
        t = db.query(models.Teacher).options(joinedload(models.Teacher.user)).filter(
            models.Teacher.user_id == user.id).first()
        if not t:
            raise HTTPException(status_code=400, detail="Your account is not linked to a teacher profile")
        if teacher_id and teacher_id != t.id:
            raise HTTPException(status_code=403, detail="You may only view your own attendance calendar")
        return t
    if not teacher_id:
        raise HTTPException(status_code=400, detail="teacher_id is required")
    t = db.query(models.Teacher).options(joinedload(models.Teacher.user)).filter(
        models.Teacher.id == teacher_id).first()
    if not t:
        raise HTTPException(status_code=404, detail="Teacher not found")
    if user.role != models.RoleEnum.super_admin and t.school_id != user.school_id:
        raise HTTPException(status_code=403, detail="Different school")
    return t


def _holidays(db: Session, school_id: int, start: date_cls, end: date_cls) -> dict[date_cls, str]:
    """Dates closed by the academic calendar, mapped to the event title."""
    out: dict[date_cls, str] = {}
    for ev in db.query(models.CalendarEvent).filter(
        models.CalendarEvent.school_id == school_id,
        models.CalendarEvent.is_holiday.is_(True),
    ):
        cur, last = ev.date, (ev.end_date or ev.date)
        while cur <= last:
            if start <= cur <= end:
                out[cur] = ev.title
            cur += timedelta(days=1)
    return out


def _build_days(db: Session, teacher: models.Teacher, start: date_cls, end: date_cls) -> list[schemas.AttendanceDayOut]:
    school = db.query(models.School).filter(models.School.id == teacher.school_id).first()
    working_days = school.working_days if school else 5
    holidays = _holidays(db, teacher.school_id, start, end)

    leaves = db.query(models.Leave).filter(
        models.Leave.teacher_id == teacher.id,
        models.Leave.status == models.LeaveStatus.approved,
    ).all()
    duties = db.query(models.OnDuty).filter(
        models.OnDuty.teacher_id == teacher.id,
        models.OnDuty.status == models.OnDutyStatus.approved,
    ).all()

    # substitutes covering this teacher's slots, keyed by date
    subs = (
        db.query(models.Substitution)
        .options(
            joinedload(models.Substitution.substitute_teacher).joinedload(models.Teacher.user),
            joinedload(models.Substitution.timetable),
        )
        .join(models.Timetable, models.Substitution.timetable_id == models.Timetable.id)
        .filter(models.Timetable.teacher_id == teacher.id,
                models.Substitution.date >= start, models.Substitution.date <= end)
        .all()
    )
    subs_by_date: dict[date_cls, list[models.Substitution]] = {}
    for s in subs:
        subs_by_date.setdefault(s.date, []).append(s)

    days: list[schemas.AttendanceDayOut] = []
    cur = start
    while cur <= end:
        cover = subs_by_date.get(cur, [])
        sub_names = [f"P{s.timetable.period}: {s.substitute_teacher.user.name}"
                     for s in sorted(cover, key=lambda x: x.timetable.period)
                     if s.substitute_teacher and s.substitute_teacher.user]

        lv = next((l for l in leaves if l.date <= cur <= (l.end_date or l.date)), None)
        od = next((d for d in duties if d.date <= cur <= (d.end_date or d.date)), None)

        if cur in holidays:
            day = schemas.AttendanceDayOut(date=cur, status="holiday", colour="grey",
                                           detail=holidays[cur])
        elif cur.weekday() >= working_days:
            day = schemas.AttendanceDayOut(date=cur, status="non_working", colour="grey",
                                           detail="Non-working day")
        elif lv:
            day = schemas.AttendanceDayOut(
                date=cur, status="leave", colour="red",
                detail=lv.reason or "On leave", leave_id=lv.id,
                affected_periods=sorted({s.timetable.period for s in cover}),
                substitutes=sub_names,
            )
        elif od:
            periods = [s.period for s in slots_for_teacher_on_weekday(db, teacher.id, cur.weekday())
                       if _od_covers_period(od, s.period)]
            day = schemas.AttendanceDayOut(
                date=cur, status="on_duty", colour="yellow",
                detail=f"{od.duty_type}" + (f" - {od.location}" if od.location else ""),
                on_duty_id=od.id, duty_type=od.duty_type,
                affected_periods=sorted(periods), substitutes=sub_names,
            )
        else:
            day = schemas.AttendanceDayOut(date=cur, status="present", colour="green")
        days.append(day)
        cur += timedelta(days=1)
    return days


@router.get("/calendar", response_model=schemas.AttendanceCalendarOut)
def attendance_calendar(
    year: int = Query(..., ge=2000, le=2100),
    month: int = Query(..., ge=1, le=12),
    teacher_id: int | None = None,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """Monthly attendance for one teacher. Read-only and always derived."""
    teacher = _resolve_teacher(db, user, teacher_id)
    last = calendar_mod.monthrange(year, month)[1]
    days = _build_days(db, teacher, date_cls(year, month, 1), date_cls(year, month, last))

    summary: dict[str, int] = {}
    for d in days:
        summary[d.status] = summary.get(d.status, 0) + 1
    return schemas.AttendanceCalendarOut(
        teacher_id=teacher.id,
        teacher_name=teacher.user.name if teacher.user else "",
        year=year, month=month, summary=summary, days=days,
    )


@router.get("/day", response_model=schemas.AttendanceDayOut)
def attendance_day(
    on_date: date_cls = Query(..., alias="date"),
    teacher_id: int | None = None,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """Full detail for one day - what the calendar shows when a date is clicked."""
    teacher = _resolve_teacher(db, user, teacher_id)
    return _build_days(db, teacher, on_date, on_date)[0]


@router.get("/substitute-load")
def substitute_load(
    start: date_cls = Query(...),
    end: date_cls = Query(...),
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """Substitute hours per teacher, visible to EVERY authenticated user.

    Substitution duty is shared institutional load, so who is covering how many
    periods is deliberately transparent to all teachers - not just admins."""
    if user.role == models.RoleEnum.super_admin:
        school_id = None
    else:
        school_id = user.school_id
    q = (
        db.query(models.Substitution)
        .options(joinedload(models.Substitution.substitute_teacher).joinedload(models.Teacher.user))
        .filter(models.Substitution.date >= start, models.Substitution.date <= end)
    )
    rows = q.all()
    by_teacher: dict[int, dict] = {}
    for s in rows:
        t = s.substitute_teacher
        if not t or (school_id and t.school_id != school_id):
            continue
        e = by_teacher.setdefault(t.id, {
            "teacher_id": t.id,
            "teacher_name": t.user.name if t.user else "",
            "substitute_periods": 0,
            "dates": set(),
        })
        e["substitute_periods"] += 1
        e["dates"].add(str(s.date))
    items = sorted(
        [{**v, "days_covered": len(v.pop("dates"))} for v in by_teacher.values()],
        key=lambda x: -x["substitute_periods"],
    )
    return {
        "start": start, "end": end,
        "total_substitute_periods": sum(i["substitute_periods"] for i in items),
        "teachers": items,
    }
