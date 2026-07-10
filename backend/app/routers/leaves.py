from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.auth import get_current_user, require_roles
from app.crud_factory import log_action
from app.substitution_engine import find_substitute, leave_date_range, slots_for_teacher_on_weekday
from app import models, schemas

router = APIRouter(prefix="/leaves", tags=["leaves"])
ADMIN_ROLES = (models.RoleEnum.super_admin, models.RoleEnum.school_admin)


def _with_joins(query):
    return query.options(joinedload(models.Leave.teacher).joinedload(models.Teacher.user))


def to_leave_out(row: models.Leave) -> schemas.LeaveOut:
    return schemas.LeaveOut(
        id=row.id,
        teacher_id=row.teacher_id,
        teacher_name=row.teacher.user.name if row.teacher else "",
        school_id=row.school_id,
        date=row.date,
        end_date=row.end_date,
        reason=row.reason,
        status=row.status,
        decision_note=row.decision_note,
        reviewed_by=row.reviewed_by,
        reviewed_at=row.reviewed_at,
        created_at=row.created_at,
    )


def get_or_404(db: Session, leave_id: int, user: models.User) -> models.Leave:
    row = _with_joins(db.query(models.Leave)).filter(models.Leave.id == leave_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Leave not found")
    if user.role == models.RoleEnum.teacher and row.teacher.user_id != user.id:
        raise HTTPException(status_code=403, detail="Not your leave request")
    if user.role != models.RoleEnum.super_admin and row.school_id != user.school_id:
        raise HTTPException(status_code=403, detail="Leave belongs to a different school")
    return row


@router.post("", response_model=schemas.LeaveOut, status_code=201)
def apply_leave(
    payload: schemas.LeaveCreate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    if user.role == models.RoleEnum.teacher:
        teacher = db.query(models.Teacher).filter(models.Teacher.user_id == user.id).first()
        if not teacher:
            raise HTTPException(status_code=400, detail="No teacher profile linked to this account")
        teacher_id = teacher.id
    else:
        if not payload.teacher_id:
            raise HTTPException(status_code=400, detail="teacher_id is required for admin-submitted leave")
        teacher = db.query(models.Teacher).filter(models.Teacher.id == payload.teacher_id).first()
        if not teacher:
            raise HTTPException(status_code=404, detail="Teacher not found")
        if user.role != models.RoleEnum.super_admin and teacher.school_id != user.school_id:
            raise HTTPException(status_code=403, detail="Teacher belongs to a different school")
        teacher_id = teacher.id

    end_date = payload.end_date or payload.date
    if end_date < payload.date:
        raise HTTPException(status_code=400, detail="end_date cannot be before date")

    row = models.Leave(
        teacher_id=teacher_id,
        school_id=teacher.school_id,
        date=payload.date,
        end_date=payload.end_date,
        reason=payload.reason,
        status=models.LeaveStatus.pending,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    log_action(db, user.id, "apply_leave", f"leave_id={row.id} teacher_id={teacher_id}")
    return to_leave_out(_with_joins(db.query(models.Leave)).filter(models.Leave.id == row.id).first())


@router.get("")
def list_leaves(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    status: models.LeaveStatus | None = None,
    teacher_id: int | None = None,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    query = _with_joins(db.query(models.Leave))
    if user.role == models.RoleEnum.teacher:
        teacher = db.query(models.Teacher).filter(models.Teacher.user_id == user.id).first()
        query = query.filter(models.Leave.teacher_id == (teacher.id if teacher else -1))
    elif user.role != models.RoleEnum.super_admin:
        query = query.filter(models.Leave.school_id == user.school_id)
    if status:
        query = query.filter(models.Leave.status == status)
    if teacher_id:
        query = query.filter(models.Leave.teacher_id == teacher_id)
    total = query.count()
    items = query.order_by(models.Leave.created_at.desc()).offset((page - 1) * limit).limit(limit).all()
    return {"items": [to_leave_out(i) for i in items], "total": total, "page": page, "limit": limit}


@router.get("/{leave_id}", response_model=schemas.LeaveOut)
def get_leave(leave_id: int, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    return to_leave_out(get_or_404(db, leave_id, user))


@router.delete("/{leave_id}", status_code=204)
def cancel_leave(leave_id: int, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    row = get_or_404(db, leave_id, user)
    if row.status != models.LeaveStatus.pending:
        raise HTTPException(status_code=400, detail="Only pending leave requests can be cancelled")
    db.delete(row)
    db.commit()
    log_action(db, user.id, "cancel_leave", f"leave_id={leave_id}")


def _notify(db: Session, user_id: int, message: str):
    db.add(models.Notification(user_id=user_id, message=message))


@router.post("/{leave_id}/reject", response_model=schemas.LeaveOut)
def reject_leave(
    leave_id: int,
    payload: schemas.LeaveDecision,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_roles(*ADMIN_ROLES)),
):
    row = get_or_404(db, leave_id, user)
    if row.status != models.LeaveStatus.pending:
        raise HTTPException(status_code=400, detail="Leave has already been reviewed")
    row.status = models.LeaveStatus.rejected
    row.decision_note = payload.note
    row.reviewed_by = user.id
    row.reviewed_at = datetime.utcnow()
    _notify(db, row.teacher.user_id, f"Your leave request for {row.date} was rejected." + (f" Note: {payload.note}" if payload.note else ""))
    db.commit()
    db.refresh(row)
    log_action(db, user.id, "reject_leave", f"leave_id={leave_id}")
    return to_leave_out(row)


@router.get("/{leave_id}/gaps", response_model=list[schemas.UncoveredSlotOut])
def get_leave_gaps(leave_id: int, db: Session = Depends(get_db), user: models.User = Depends(require_roles(*ADMIN_ROLES))):
    """Re-derive which slots for an approved leave still have no Substitution
    row (e.g. left uncovered at approval time, or manually deleted since).
    Lets the admin UI resurface the manual-assignment worklist any time
    later, without depending on the one-shot /approve response."""
    row = get_or_404(db, leave_id, user)
    if row.status != models.LeaveStatus.approved:
        return []
    gaps = []
    for on_date in leave_date_range(row):
        day_of_week = on_date.weekday()
        slots = slots_for_teacher_on_weekday(db, row.teacher_id, day_of_week)
        for slot in slots:
            existing = db.query(models.Substitution).filter(
                models.Substitution.timetable_id == slot.id,
                models.Substitution.date == on_date,
            ).first()
            if existing:
                continue
            label = f"{slot.section.class_.name} {slot.section.name}" if slot.section else "section"
            gaps.append(schemas.UncoveredSlotOut(
                timetable_id=slot.id,
                date=on_date,
                day_of_week=day_of_week,
                period=slot.period,
                section_name=label,
                subject_name=slot.subject.name if slot.subject else None,
                activity_name=slot.activity.name if slot.activity else None,
                reason="Not yet covered — needs manual assignment.",
            ))
    return gaps


@router.post("/{leave_id}/approve", response_model=schemas.LeaveApprovalResult)
def approve_leave(
    leave_id: int,
    payload: schemas.LeaveDecision,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_roles(*ADMIN_ROLES)),
):
    """Approve the leave, then run the Auto Substitute Engine for every
    master-timetable slot the teacher would have taught across the leave's
    date range. Never touches the master Timetable rows (Layer 2 overlay) —
    only writes Substitution rows."""
    row = get_or_404(db, leave_id, user)
    if row.status != models.LeaveStatus.pending:
        raise HTTPException(status_code=400, detail="Leave has already been reviewed")

    row.status = models.LeaveStatus.approved
    row.decision_note = payload.note
    row.reviewed_by = user.id
    row.reviewed_at = datetime.utcnow()
    db.flush()

    uncovered: list[schemas.UncoveredSlotOut] = []
    created = 0
    notified_teachers: dict[int, list[str]] = {}

    for on_date in leave_date_range(row):
        day_of_week = on_date.weekday()
        slots = slots_for_teacher_on_weekday(db, row.teacher_id, day_of_week)
        for slot in slots:
            existing = db.query(models.Substitution).filter(
                models.Substitution.timetable_id == slot.id,
                models.Substitution.date == on_date,
            ).first()
            if existing:
                continue
            match = find_substitute(db, slot, on_date, row.teacher_id)
            label = f"{slot.section.class_.name} {slot.section.name}" if slot.section else "section"
            subject_or_activity = slot.subject.name if slot.subject else (slot.activity.name if slot.activity else None)
            if match.substitute_teacher_id is None:
                uncovered.append(schemas.UncoveredSlotOut(
                    timetable_id=slot.id,
                    date=on_date,
                    day_of_week=day_of_week,
                    period=slot.period,
                    section_name=label,
                    subject_name=slot.subject.name if slot.subject else None,
                    activity_name=slot.activity.name if slot.activity else None,
                    reason=match.reason,
                ))
                continue
            sub = models.Substitution(
                leave_id=row.id,
                timetable_id=slot.id,
                substitute_teacher_id=match.substitute_teacher_id,
                date=on_date,
                method=match.method,
                reason=match.reason,
                assigned_by=None,
            )
            db.add(sub)
            db.flush()  # so the next _is_free/workload check in this loop sees it
            created += 1
            sub_teacher = db.query(models.Teacher).options(joinedload(models.Teacher.user)).filter(
                models.Teacher.id == match.substitute_teacher_id
            ).first()
            if sub_teacher:
                notified_teachers.setdefault(sub_teacher.user_id, []).append(
                    f"{on_date} period {slot.period} ({subject_or_activity or 'class'}, {label})"
                )

    for user_id, slots_desc in notified_teachers.items():
        summary = "; ".join(slots_desc[:5]) + (f" and {len(slots_desc) - 5} more" if len(slots_desc) > 5 else "")
        _notify(db, user_id, f"You've been assigned as a substitute: {summary}.")
    _notify(db, row.teacher.user_id, f"Your leave request for {row.date}"
            + (f" to {row.end_date}" if row.end_date else "") + " was approved.")

    db.commit()
    db.refresh(row)
    log_action(db, user.id, "approve_leave", f"leave_id={leave_id} substitutions_created={created} uncovered={len(uncovered)}")

    message = f"Leave approved. {created} slot(s) auto-substituted."
    if uncovered:
        message += f" {len(uncovered)} slot(s) could not be covered and need manual assignment."

    return schemas.LeaveApprovalResult(
        leave=to_leave_out(row),
        substitutions_created=created,
        uncovered_slots=uncovered,
        message=message,
    )
