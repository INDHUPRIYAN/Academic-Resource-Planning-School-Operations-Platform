"""On Duty (Daily Operations, Layer 2).

The teacher is physically IN school but cannot take their classes (exam duty,
office work, inspection, training, ...). So:

  * attendance stays PRESENT (yellow on the calendar, not a leave), and
  * only the periods the duty covers are handed to substitutes.

Exactly like Leave, this is an overlay: the Master Timetable is never modified,
we only write Substitution rows. Approval is by principal / vice-principal
(or school/super admin).
"""
from datetime import datetime, date as date_cls

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload

from app import models, schemas
from app.auth import get_current_user, require_roles, APPROVER_ROLES
from app.crud_factory import log_action
from app.database import get_db
from app.services.substitute_queue import build_queue
from app.substitution_engine import on_duty_date_range, slots_for_on_duty

router = APIRouter(prefix="/on-duty", tags=["on-duty"])


def to_out(row: models.OnDuty) -> schemas.OnDutyOut:
    return schemas.OnDutyOut(
        id=row.id,
        teacher_id=row.teacher_id,
        teacher_name=row.teacher.user.name if row.teacher and row.teacher.user else "",
        school_id=row.school_id,
        date=row.date,
        end_date=row.end_date,
        start_period=row.start_period,
        end_period=row.end_period,
        duty_type=row.duty_type,
        description=row.description,
        location=row.location,
        status=row.status,
        decision_note=row.decision_note,
        requested_by=row.requested_by,
        assigned_by=row.assigned_by,
        reviewed_by=row.reviewed_by,
        reviewed_at=row.reviewed_at,
        created_at=row.created_at,
    )


def _with_joins(q):
    return q.options(joinedload(models.OnDuty.teacher).joinedload(models.Teacher.user))


def _my_teacher(db: Session, user: models.User) -> models.Teacher:
    t = db.query(models.Teacher).filter(models.Teacher.user_id == user.id).first()
    if not t:
        raise HTTPException(status_code=400, detail="Your account is not linked to a teacher profile")
    return t


def get_or_404(db: Session, od_id: int, user: models.User) -> models.OnDuty:
    row = _with_joins(db.query(models.OnDuty)).filter(models.OnDuty.id == od_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="On-duty record not found")
    if user.role == models.RoleEnum.teacher:
        t = _my_teacher(db, user)
        if row.teacher_id != t.id:
            raise HTTPException(status_code=403, detail="Not your on-duty record")
    elif user.role != models.RoleEnum.super_admin and row.school_id != user.school_id:
        raise HTTPException(status_code=403, detail="Different school")
    return row


def _notify(db: Session, user_id: int, message: str):
    db.add(models.Notification(user_id=user_id, message=message))


@router.get("/duty-types")
def duty_types():
    """The official duty categories (config-driven UI, no hardcoded frontend list)."""
    return {"duty_types": schemas.DUTY_TYPES}


@router.post("", response_model=schemas.OnDutyOut, status_code=201)
def create_on_duty(
    payload: schemas.OnDutyCreate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """A teacher requests on-duty for themselves; an admin/principal may raise it for
    any teacher. Either way it starts PENDING and must be approved before it has any
    effect on the timetable."""
    if user.role == models.RoleEnum.teacher:
        teacher = _my_teacher(db, user)
        assigned_by = None
    else:
        if not payload.teacher_id:
            raise HTTPException(status_code=400, detail="teacher_id is required")
        teacher = db.query(models.Teacher).filter(models.Teacher.id == payload.teacher_id).first()
        if not teacher:
            raise HTTPException(status_code=404, detail="Teacher not found")
        if user.role != models.RoleEnum.super_admin and teacher.school_id != user.school_id:
            raise HTTPException(status_code=403, detail="Different school")
        assigned_by = user.id

    if payload.duty_type not in schemas.DUTY_TYPES:
        raise HTTPException(status_code=400, detail=f"Unknown duty_type. Allowed: {', '.join(schemas.DUTY_TYPES)}")
    if payload.end_date and payload.end_date < payload.date:
        raise HTTPException(status_code=400, detail="end_date cannot be before date")
    if (payload.start_period is None) != (payload.end_period is None):
        raise HTTPException(status_code=400, detail="Provide both start_period and end_period, or neither (whole day)")
    if payload.start_period is not None and payload.end_period < payload.start_period:
        raise HTTPException(status_code=400, detail="end_period cannot be before start_period")

    row = models.OnDuty(
        teacher_id=teacher.id,
        school_id=teacher.school_id,
        date=payload.date,
        end_date=payload.end_date,
        start_period=payload.start_period,
        end_period=payload.end_period,
        duty_type=payload.duty_type,
        description=payload.description,
        location=payload.location,
        status=models.OnDutyStatus.pending,
        requested_by=user.id,
        assigned_by=assigned_by,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    log_action(db, user.id, "create_on_duty", f"on_duty_id={row.id} teacher_id={teacher.id} type={payload.duty_type}")
    _notify(db, teacher.user_id, f"On-duty ({payload.duty_type}) recorded for {payload.date}. Awaiting approval.")
    db.commit()
    return to_out(get_or_404(db, row.id, user))


@router.get("")
def list_on_duty(
    status: models.OnDutyStatus | None = None,
    teacher_id: int | None = None,
    start: date_cls | None = None,
    end: date_cls | None = None,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    q = _with_joins(db.query(models.OnDuty))
    if user.role == models.RoleEnum.teacher:
        q = q.filter(models.OnDuty.teacher_id == _my_teacher(db, user).id)
    elif user.role != models.RoleEnum.super_admin:
        q = q.filter(models.OnDuty.school_id == user.school_id)
    if status:
        q = q.filter(models.OnDuty.status == status)
    if teacher_id:
        q = q.filter(models.OnDuty.teacher_id == teacher_id)
    if start:
        q = q.filter(models.OnDuty.date >= start)
    if end:
        q = q.filter(models.OnDuty.date <= end)
    total = q.count()
    rows = q.order_by(models.OnDuty.date.desc()).offset((page - 1) * limit).limit(limit).all()
    return {"items": [to_out(r) for r in rows], "total": total, "page": page, "limit": limit}


@router.post("/{od_id}/approve", response_model=schemas.OnDutyApprovalResult)
def approve_on_duty(
    od_id: int,
    payload: schemas.OnDutyDecision,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_roles(*APPROVER_ROLES)),
):
    """Approve, then auto-substitute every master-timetable slot the duty takes the
    teacher away from. Layer 2 only - no Timetable row is ever modified."""
    row = get_or_404(db, od_id, user)
    if row.status != models.OnDutyStatus.pending:
        raise HTTPException(status_code=400, detail="This on-duty request has already been reviewed")

    row.status = models.OnDutyStatus.approved
    row.decision_note = payload.note
    row.reviewed_by = user.id
    row.reviewed_at = datetime.utcnow()
    db.flush()

    uncovered: list[schemas.UncoveredSlotOut] = []
    created = 0
    notified: dict[int, list[str]] = {}

    for on_date in on_duty_date_range(row):
        for slot in slots_for_on_duty(db, row, on_date):
            existing = db.query(models.Substitution).filter(
                models.Substitution.timetable_id == slot.id,
                models.Substitution.date == on_date,
            ).first()
            if existing:
                continue
            # Build the FULL ranked queue: rank 1 is assigned, the rest wait as backups
            # so a decline can be promoted instantly.
            sub, _cands, msg = build_queue(db, slot, on_date, row.teacher_id, on_duty_id=row.id)
            label = f"{slot.section.class_.name} {slot.section.name}" if slot.section else "section"
            what = slot.subject.name if slot.subject else (slot.activity.name if slot.activity else None)
            if sub is None:
                uncovered.append(schemas.UncoveredSlotOut(
                    timetable_id=slot.id, date=on_date, day_of_week=on_date.weekday(),
                    period=slot.period, section_name=label,
                    subject_name=slot.subject.name if slot.subject else None,
                    activity_name=slot.activity.name if slot.activity else None,
                    reason=msg,
                ))
                continue
            created += 1
            st = db.query(models.Teacher).options(joinedload(models.Teacher.user)).filter(
                models.Teacher.id == sub.substitute_teacher_id).first()
            if st:
                notified.setdefault(st.user_id, []).append(
                    f"{on_date} period {slot.period} ({what or 'class'}, {label})")

    for uid, descs in notified.items():
        summary = "; ".join(descs[:5]) + (f" and {len(descs) - 5} more" if len(descs) > 5 else "")
        _notify(db, uid, f"You've been assigned as a substitute: {summary}.")
    _notify(db, row.teacher.user_id,
            f"Your on-duty ({row.duty_type}) for {row.date} was approved. "
            f"{created} of your period(s) will be covered by substitutes.")

    db.commit()
    db.refresh(row)
    log_action(db, user.id, "approve_on_duty",
               f"on_duty_id={od_id} substitutions_created={created} uncovered={len(uncovered)}")

    msg = f"On-duty approved. {created} period(s) auto-substituted."
    if uncovered:
        msg += f" {len(uncovered)} period(s) could not be covered and need manual assignment."
    return schemas.OnDutyApprovalResult(
        on_duty=to_out(row), substitutions_created=created, uncovered_slots=uncovered, message=msg,
    )


@router.post("/{od_id}/reject", response_model=schemas.OnDutyOut)
def reject_on_duty(
    od_id: int,
    payload: schemas.OnDutyDecision,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_roles(*APPROVER_ROLES)),
):
    row = get_or_404(db, od_id, user)
    if row.status != models.OnDutyStatus.pending:
        raise HTTPException(status_code=400, detail="This on-duty request has already been reviewed")
    row.status = models.OnDutyStatus.rejected
    row.decision_note = payload.note
    row.reviewed_by = user.id
    row.reviewed_at = datetime.utcnow()
    _notify(db, row.teacher.user_id,
            f"Your on-duty ({row.duty_type}) for {row.date} was rejected."
            + (f" Note: {payload.note}" if payload.note else ""))
    db.commit()
    db.refresh(row)
    log_action(db, user.id, "reject_on_duty", f"on_duty_id={od_id}")
    return to_out(row)


@router.post("/{od_id}/cancel", response_model=schemas.OnDutyOut)
def cancel_on_duty(
    od_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """Cancelling an approved on-duty releases the substitutes it created."""
    row = get_or_404(db, od_id, user)
    if row.status == models.OnDutyStatus.cancelled:
        raise HTTPException(status_code=400, detail="Already cancelled")

    released = db.query(models.Substitution).filter(models.Substitution.on_duty_id == row.id).delete(
        synchronize_session=False)
    row.status = models.OnDutyStatus.cancelled
    db.commit()
    db.refresh(row)
    log_action(db, user.id, "cancel_on_duty", f"on_duty_id={od_id} substitutions_released={released}")
    return to_out(row)
