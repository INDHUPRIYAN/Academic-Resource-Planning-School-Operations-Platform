"""
Exam Module (Phase 6).

Exam timetable management: scheduling individual exams (subject + section +
date/time + optional room + optional invigilator), and a bulk generator
that greedily fills a date range with one exam per (section, subject) pair
that section is taught, avoiding double-booking a section, an invigilator,
or a room.

Design note (see handoff/README "Next steps" for the original open
question): this uses a straightforward greedy earliest-available-slot
placement rather than OR-Tools CP-SAT. Exam scheduling here has a much
looser constraint set than the master timetable (no weekly-hours balancing,
no teacher-subject matching requirement, no day-by-day period grid to
fill) — the only real constraints are "don't double-book a section, a
room, or an invigilator at the same date/time", which a greedy placement
satisfies deterministically without needing a solver. If a school later
wants smarter invigilator load-balancing or fixed per-subject exam
durations, revisit with CP-SAT then; not needed for v1.

Exams are their own model/table (not a Layer-2 overlay like Substitution/
Swap) since an exam period doesn't correspond 1:1 with a master Timetable
row — it's a separate schedule entirely, on separate (usually non-teaching)
days.
"""
from datetime import datetime, date as date_cls, time as time_cls, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.auth import get_current_user, require_roles
from app.crud_factory import log_action
from app import models, schemas

router = APIRouter(prefix="/exams", tags=["exams"])
ADMIN_ROLES = (models.RoleEnum.super_admin, models.RoleEnum.school_admin)


def _with_joins(query):
    return query.options(
        joinedload(models.Exam.subject),
        joinedload(models.Exam.section).joinedload(models.Section.class_),
        joinedload(models.Exam.resource),
        joinedload(models.Exam.invigilator).joinedload(models.Teacher.user),
    )


def to_exam_out(row: models.Exam) -> schemas.ExamOut:
    return schemas.ExamOut(
        id=row.id,
        school_id=row.school_id,
        subject_id=row.subject_id,
        subject_name=row.subject.name if row.subject else "",
        section_id=row.section_id,
        section_name=f"{row.section.class_.name} {row.section.name}" if row.section and row.section.class_ else "",
        resource_id=row.resource_id,
        resource_name=row.resource.name if row.resource else None,
        invigilator_id=row.invigilator_id,
        invigilator_name=row.invigilator.user.name if row.invigilator else None,
        date=row.date,
        start_time=row.start_time,
        end_time=row.end_time,
    )


def get_or_404(db: Session, exam_id: int, user: models.User) -> models.Exam:
    row = _with_joins(db.query(models.Exam)).filter(models.Exam.id == exam_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Exam not found")
    if user.role != models.RoleEnum.super_admin and row.school_id != user.school_id:
        raise HTTPException(status_code=403, detail="Exam belongs to a different school")
    return row


def _overlaps(start_a: time_cls, end_a: time_cls, start_b: time_cls, end_b: time_cls) -> bool:
    return start_a < end_b and start_b < end_a


def _conflict_reason(db: Session, *, exam_date: date_cls, start_time: time_cls, end_time: time_cls,
                      section_id: int, resource_id: int | None, invigilator_id: int | None,
                      exclude_exam_id: int | None = None) -> str | None:
    """Return a human-readable conflict reason, or None if the slot is free.
    Checked against other Exam rows only (a section/room/invigilator can be
    double-booked across exams, but not within them)."""
    query = db.query(models.Exam).filter(models.Exam.date == exam_date)
    if exclude_exam_id:
        query = query.filter(models.Exam.id != exclude_exam_id)
    same_day = query.all()

    for other in same_day:
        if not _overlaps(start_time, end_time, other.start_time, other.end_time):
            continue
        if other.section_id == section_id:
            return f"section already has an overlapping exam at {other.start_time}-{other.end_time}"
        if resource_id and other.resource_id == resource_id:
            return f"room is already booked for an overlapping exam at {other.start_time}-{other.end_time}"
        if invigilator_id and other.invigilator_id == invigilator_id:
            return f"invigilator is already assigned to an overlapping exam at {other.start_time}-{other.end_time}"
    return None


@router.post("", response_model=schemas.ExamOut, status_code=201)
def create_exam(
    payload: schemas.ExamCreate,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_roles(*ADMIN_ROLES)),
):
    if payload.end_time <= payload.start_time:
        raise HTTPException(status_code=400, detail="end_time must be after start_time")

    subject = db.query(models.Subject).filter(models.Subject.id == payload.subject_id).first()
    section = db.query(models.Section).filter(models.Section.id == payload.section_id).first()
    if not subject or not section:
        raise HTTPException(status_code=404, detail="Subject or section not found")
    if user.role != models.RoleEnum.super_admin and subject.school_id != user.school_id:
        raise HTTPException(status_code=403, detail="Subject belongs to a different school")

    if payload.resource_id:
        resource = db.query(models.Resource).filter(models.Resource.id == payload.resource_id).first()
        if not resource:
            raise HTTPException(status_code=404, detail="Resource not found")
    if payload.invigilator_id:
        invigilator = db.query(models.Teacher).filter(models.Teacher.id == payload.invigilator_id).first()
        if not invigilator:
            raise HTTPException(status_code=404, detail="Invigilator (teacher) not found")

    conflict = _conflict_reason(
        db, exam_date=payload.date, start_time=payload.start_time, end_time=payload.end_time,
        section_id=payload.section_id, resource_id=payload.resource_id, invigilator_id=payload.invigilator_id,
    )
    if conflict:
        raise HTTPException(status_code=409, detail=f"Cannot schedule: {conflict}")

    row = models.Exam(
        school_id=subject.school_id,
        subject_id=payload.subject_id,
        section_id=payload.section_id,
        resource_id=payload.resource_id,
        invigilator_id=payload.invigilator_id,
        date=payload.date,
        start_time=payload.start_time,
        end_time=payload.end_time,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    log_action(db, user.id, "create_exam", f"exam_id={row.id}")
    return to_exam_out(get_or_404(db, row.id, user))


@router.get("")
def list_exams(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=500),
    date: date_cls | None = None,
    start_date: date_cls | None = None,
    end_date: date_cls | None = None,
    section_id: int | None = None,
    subject_id: int | None = None,
    invigilator_id: int | None = None,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    query = _with_joins(db.query(models.Exam))
    if user.role != models.RoleEnum.super_admin:
        query = query.filter(models.Exam.school_id == user.school_id)
    if date:
        query = query.filter(models.Exam.date == date)
    if start_date:
        query = query.filter(models.Exam.date >= start_date)
    if end_date:
        query = query.filter(models.Exam.date <= end_date)
    if section_id:
        query = query.filter(models.Exam.section_id == section_id)
    if subject_id:
        query = query.filter(models.Exam.subject_id == subject_id)
    if invigilator_id:
        query = query.filter(models.Exam.invigilator_id == invigilator_id)
    total = query.count()
    items = query.order_by(models.Exam.date, models.Exam.start_time).offset((page - 1) * limit).limit(limit).all()
    return {"items": [to_exam_out(i) for i in items], "total": total, "page": page, "limit": limit}


@router.get("/{exam_id}", response_model=schemas.ExamOut)
def get_exam(exam_id: int, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    return to_exam_out(get_or_404(db, exam_id, user))


@router.put("/{exam_id}", response_model=schemas.ExamOut)
def update_exam(
    exam_id: int,
    payload: schemas.ExamUpdate,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_roles(*ADMIN_ROLES)),
):
    row = get_or_404(db, exam_id, user)
    new_date = payload.date if payload.date is not None else row.date
    new_start = payload.start_time if payload.start_time is not None else row.start_time
    new_end = payload.end_time if payload.end_time is not None else row.end_time
    new_section_id = payload.section_id if payload.section_id is not None else row.section_id
    new_resource_id = payload.resource_id if payload.resource_id is not None else row.resource_id
    new_invigilator_id = payload.invigilator_id if payload.invigilator_id is not None else row.invigilator_id

    if new_end <= new_start:
        raise HTTPException(status_code=400, detail="end_time must be after start_time")

    conflict = _conflict_reason(
        db, exam_date=new_date, start_time=new_start, end_time=new_end,
        section_id=new_section_id, resource_id=new_resource_id, invigilator_id=new_invigilator_id,
        exclude_exam_id=row.id,
    )
    if conflict:
        raise HTTPException(status_code=409, detail=f"Cannot reschedule: {conflict}")

    if payload.subject_id is not None:
        row.subject_id = payload.subject_id
    row.section_id = new_section_id
    row.resource_id = new_resource_id
    row.invigilator_id = new_invigilator_id
    row.date = new_date
    row.start_time = new_start
    row.end_time = new_end
    db.commit()
    db.refresh(row)
    log_action(db, user.id, "update_exam", f"exam_id={exam_id}")
    return to_exam_out(get_or_404(db, exam_id, user))


@router.delete("/{exam_id}", status_code=204)
def delete_exam(exam_id: int, db: Session = Depends(get_db), user: models.User = Depends(require_roles(*ADMIN_ROLES))):
    row = get_or_404(db, exam_id, user)
    db.delete(row)
    db.commit()
    log_action(db, user.id, "delete_exam", f"exam_id={exam_id}")


def _add_minutes(t: time_cls, minutes: int) -> time_cls:
    dt = datetime.combine(date_cls.today(), t) + timedelta(minutes=minutes)
    return dt.time()


def _daterange_weekdays(start: date_cls, end: date_cls, working_days: int):
    """Yield each date from start to end (inclusive) whose weekday() index
    is < working_days — same Mon-Fri-by-default convention as
    School.working_days / Timetable.day_of_week elsewhere in the app."""
    d = start
    while d <= end:
        if d.weekday() < working_days:
            yield d
        d += timedelta(days=1)


@router.post("/generate", response_model=schemas.ExamGenerateResponse)
def generate_exams(
    payload: schemas.ExamGenerateRequest,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_roles(*ADMIN_ROLES)),
):
    if user.role == models.RoleEnum.super_admin:
        if not payload.school_id:
            raise HTTPException(status_code=400, detail="school_id is required for super_admin")
        school_id = payload.school_id
    else:
        school_id = user.school_id

    if payload.end_date < payload.start_date:
        raise HTTPException(status_code=400, detail="end_date must be on or after start_date")
    if payload.exams_per_day < 1:
        raise HTTPException(status_code=400, detail="exams_per_day must be at least 1")

    school = db.query(models.School).filter(models.School.id == school_id).first()
    if not school:
        raise HTTPException(status_code=404, detail="School not found")

    section_ids = payload.section_ids
    if not section_ids:
        section_ids = [
            s.id for s in db.query(models.Section)
            .join(models.Class, models.Section.class_id == models.Class.id)
            .filter(models.Class.school_id == school_id).all()
        ]
    if not section_ids:
        raise HTTPException(status_code=400, detail="No sections found to schedule exams for")

    # Build the (section, subject) pairs to examine: whatever subjects each
    # section is actually taught, per the master Timetable. A section with
    # no generated timetable yet simply yields no pairs (nothing to base it
    # on) rather than erroring.
    pairs: list[tuple[models.Section, models.Subject]] = []
    for section_id in section_ids:
        section = db.query(models.Section).options(joinedload(models.Section.class_)).filter(
            models.Section.id == section_id
        ).first()
        if not section or section.class_.school_id != school_id:
            continue
        subject_ids = {
            row[0] for row in db.query(models.Timetable.subject_id)
            .filter(models.Timetable.section_id == section_id, models.Timetable.subject_id.isnot(None))
            .distinct().all()
        }
        for subject_id in subject_ids:
            subject = db.query(models.Subject).filter(models.Subject.id == subject_id).first()
            if subject:
                pairs.append((section, subject))

    if not pairs:
        raise HTTPException(
            status_code=400,
            detail="No (section, subject) pairs found — generate the master timetable first, or pass section_ids for sections that already have one.",
        )

    # Build the ordered list of (date, start_time, end_time) slots.
    slots: list[tuple[date_cls, time_cls, time_cls]] = []
    for d in _daterange_weekdays(payload.start_date, payload.end_date, school.working_days):
        t = payload.daily_start_time
        for _ in range(payload.exams_per_day):
            end_t = _add_minutes(t, payload.duration_minutes)
            slots.append((d, t, end_t))
            t = _add_minutes(end_t, payload.gap_minutes)

    resource_pool = payload.resource_ids or [
        r.id for r in db.query(models.Resource).filter(models.Resource.school_id == school_id).all()
    ]
    teacher_pool = [t.id for t in db.query(models.Teacher).filter(models.Teacher.school_id == school_id).all()]

    # In-memory bookings for this generation run, seeded with anything
    # already scheduled in the target date range so we don't collide with
    # pre-existing exams either.
    existing = db.query(models.Exam).filter(
        models.Exam.school_id == school_id, models.Exam.date >= payload.start_date, models.Exam.date <= payload.end_date,
    ).all()
    booked_section: dict[tuple[date_cls, int], list[tuple[time_cls, time_cls]]] = {}
    booked_resource: dict[tuple[date_cls, int], list[tuple[time_cls, time_cls]]] = {}
    booked_teacher: dict[tuple[date_cls, int], list[tuple[time_cls, time_cls]]] = {}
    for e in existing:
        booked_section.setdefault((e.date, e.section_id), []).append((e.start_time, e.end_time))
        if e.resource_id:
            booked_resource.setdefault((e.date, e.resource_id), []).append((e.start_time, e.end_time))
        if e.invigilator_id:
            booked_teacher.setdefault((e.date, e.invigilator_id), []).append((e.start_time, e.end_time))

    def is_free(bookings: dict, key, start_t: time_cls, end_t: time_cls) -> bool:
        for s, e in bookings.get(key, []):
            if _overlaps(start_t, end_t, s, e):
                return False
        return True

    created_rows = []
    unscheduled: list[schemas.ExamGenerateUnscheduled] = []
    teacher_cursor = 0  # round-robin pointer for basic invigilator load spreading

    for section, subject in pairs:
        placed = False
        for (d, start_t, end_t) in slots:
            if not is_free(booked_section, (d, section.id), start_t, end_t):
                continue

            resource_id = subject.resource_id  # fixed room (e.g. a lab) if the subject requires one
            if resource_id is not None and not is_free(booked_resource, (d, resource_id), start_t, end_t):
                continue
            if resource_id is None and resource_pool:
                free_resource = next(
                    (rid for rid in resource_pool if is_free(booked_resource, (d, rid), start_t, end_t)), None
                )
                resource_id = free_resource  # may stay None if every room is booked — still schedulable

            invigilator_id = None
            if teacher_pool:
                for i in range(len(teacher_pool)):
                    candidate = teacher_pool[(teacher_cursor + i) % len(teacher_pool)]
                    if is_free(booked_teacher, (d, candidate), start_t, end_t):
                        invigilator_id = candidate
                        teacher_cursor = (teacher_cursor + i + 1) % len(teacher_pool)
                        break

            row = models.Exam(
                school_id=school_id, subject_id=subject.id, section_id=section.id,
                resource_id=resource_id, invigilator_id=invigilator_id,
                date=d, start_time=start_t, end_time=end_t,
            )
            db.add(row)
            created_rows.append(row)

            booked_section.setdefault((d, section.id), []).append((start_t, end_t))
            if resource_id:
                booked_resource.setdefault((d, resource_id), []).append((start_t, end_t))
            if invigilator_id:
                booked_teacher.setdefault((d, invigilator_id), []).append((start_t, end_t))
            placed = True
            break

        if not placed:
            unscheduled.append(schemas.ExamGenerateUnscheduled(
                section_id=section.id,
                section_name=f"{section.class_.name} {section.name}",
                subject_id=subject.id,
                subject_name=subject.name,
                reason="No open slot in the given date range without double-booking the section",
            ))

    db.commit()
    log_action(db, user.id, "generate_exams", f"school_id={school_id} created={len(created_rows)} unscheduled={len(unscheduled)}")
    return schemas.ExamGenerateResponse(
        school_id=school_id,
        exams_created=len(created_rows),
        unscheduled=unscheduled,
        message=(
            f"Scheduled {len(created_rows)} exam(s)."
            + (f" {len(unscheduled)} pair(s) could not be placed in this date range — widen the range or add more exams_per_day."
               if unscheduled else "")
        ),
    )
