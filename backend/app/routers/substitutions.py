from datetime import date as date_cls

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.auth import get_current_user, require_roles
from app.crud_factory import log_action
from app.substitution_engine import _is_free
from app import models, schemas

router = APIRouter(prefix="/substitutions", tags=["substitutions"])
ADMIN_ROLES = (models.RoleEnum.super_admin, models.RoleEnum.school_admin)


def _with_joins(query):
    return query.options(
        joinedload(models.Substitution.timetable).joinedload(models.Timetable.section).joinedload(models.Section.class_),
        joinedload(models.Substitution.timetable).joinedload(models.Timetable.subject),
        joinedload(models.Substitution.timetable).joinedload(models.Timetable.activity),
        joinedload(models.Substitution.timetable).joinedload(models.Timetable.teacher).joinedload(models.Teacher.user),
        joinedload(models.Substitution.substitute_teacher).joinedload(models.Teacher.user),
        joinedload(models.Substitution.leave),
    )


def to_sub_out(row: models.Substitution) -> schemas.SubstitutionOut:
    tt = row.timetable
    label = f"{tt.section.class_.name} {tt.section.name}" if tt and tt.section else ""
    return schemas.SubstitutionOut(
        id=row.id,
        leave_id=row.leave_id,
        timetable_id=row.timetable_id,
        substitute_teacher_id=row.substitute_teacher_id,
        substitute_teacher_name=row.substitute_teacher.user.name if row.substitute_teacher else "",
        original_teacher_name=tt.teacher.user.name if tt and tt.teacher else "",
        date=row.date,
        method=row.method,
        reason=row.reason,
        assigned_by=row.assigned_by,
        day_of_week=tt.day_of_week if tt else -1,
        period=tt.period if tt else -1,
        section_name=label,
        subject_name=tt.subject.name if tt and tt.subject else None,
        activity_name=tt.activity.name if tt and tt.activity else None,
    )


def scoped(query, user):
    if user.role != models.RoleEnum.super_admin:
        query = query.join(models.Timetable, models.Substitution.timetable_id == models.Timetable.id).filter(
            models.Timetable.school_id == user.school_id
        )
    return query


def get_or_404(db: Session, sub_id: int, user) -> models.Substitution:
    row = _with_joins(scoped(db.query(models.Substitution), user)).filter(models.Substitution.id == sub_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Substitution not found")
    return row


@router.get("")
def list_substitutions(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=500),
    leave_id: int | None = None,
    date: date_cls | None = None,
    teacher_id: int | None = None,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    query = _with_joins(scoped(db.query(models.Substitution), user))
    if user.role == models.RoleEnum.teacher:
        teacher = db.query(models.Teacher).filter(models.Teacher.user_id == user.id).first()
        query = query.filter(models.Substitution.substitute_teacher_id == (teacher.id if teacher else -1))
    if leave_id:
        query = query.filter(models.Substitution.leave_id == leave_id)
    if date:
        query = query.filter(models.Substitution.date == date)
    if teacher_id:
        query = query.filter(models.Substitution.substitute_teacher_id == teacher_id)
    total = query.count()
    items = query.order_by(models.Substitution.date.desc()).offset((page - 1) * limit).limit(limit).all()
    return {"items": [to_sub_out(i) for i in items], "total": total, "page": page, "limit": limit}


@router.post("", response_model=schemas.SubstitutionOut, status_code=201)
def create_substitution(
    payload: schemas.SubstitutionCreate,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_roles(*ADMIN_ROLES)),
):
    """Manual assignment, typically used for a slot the auto engine left
    uncovered. Blocks an obvious double-booking of the chosen substitute at
    that exact day/period/date, but allows override with a warning-free
    success if the admin insists (checked once here; not enforced further)."""
    leave = db.query(models.Leave).filter(models.Leave.id == payload.leave_id).first()
    if not leave:
        raise HTTPException(status_code=404, detail="Leave not found")
    if user.role != models.RoleEnum.super_admin and leave.school_id != user.school_id:
        raise HTTPException(status_code=403, detail="Leave belongs to a different school")
    slot = db.query(models.Timetable).filter(models.Timetable.id == payload.timetable_id).first()
    if not slot:
        raise HTTPException(status_code=404, detail="Timetable slot not found")
    sub_teacher = db.query(models.Teacher).filter(models.Teacher.id == payload.substitute_teacher_id).first()
    if not sub_teacher:
        raise HTTPException(status_code=404, detail="Substitute teacher not found")

    existing = db.query(models.Substitution).filter(
        models.Substitution.timetable_id == slot.id,
        models.Substitution.date == payload.date,
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail="This slot already has a substitute assigned for that date; delete it first to reassign")

    row = models.Substitution(
        leave_id=payload.leave_id,
        timetable_id=payload.timetable_id,
        substitute_teacher_id=payload.substitute_teacher_id,
        date=payload.date,
        method="manual",
        reason=f"Manually assigned by {user.name}.",
        assigned_by=user.id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    db.add(models.Notification(
        user_id=sub_teacher.user_id,
        message=f"You've been manually assigned as a substitute on {payload.date}, period {slot.period}.",
    ))
    db.commit()
    log_action(db, user.id, "create_substitution", f"id={row.id}")
    return to_sub_out(get_or_404(db, row.id, user))


@router.put("/{sub_id}", response_model=schemas.SubstitutionOut)
def update_substitution(
    sub_id: int,
    payload: schemas.SubstitutionUpdate,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_roles(*ADMIN_ROLES)),
):
    row = get_or_404(db, sub_id, user)
    tt = row.timetable
    if not _is_free(db, payload.substitute_teacher_id, tt.day_of_week, tt.period, row.date) and \
            payload.substitute_teacher_id != row.substitute_teacher_id:
        raise HTTPException(status_code=409, detail="That teacher is not free at this day/period on this date")
    row.substitute_teacher_id = payload.substitute_teacher_id
    row.method = "manual"
    row.reason = f"Reassigned by {user.name}."
    row.assigned_by = user.id
    db.commit()
    db.refresh(row)
    log_action(db, user.id, "update_substitution", f"id={sub_id}")
    return to_sub_out(get_or_404(db, sub_id, user))


@router.delete("/{sub_id}", status_code=204)
def delete_substitution(sub_id: int, db: Session = Depends(get_db), user: models.User = Depends(require_roles(*ADMIN_ROLES))):
    row = get_or_404(db, sub_id, user)
    db.delete(row)
    db.commit()
    log_action(db, user.id, "delete_substitution", f"id={sub_id}")


@router.get("/schedule", response_model=list[schemas.EffectiveSlotOut])
def effective_schedule(
    date: date_cls = Query(...),
    section_id: int | None = None,
    teacher_id: int | None = None,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """Layer 2: the master timetable for this date's weekday, with any
    approved substitutions for this exact date overlaid on top. The master
    Timetable rows are never modified — this is computed on read."""
    day_of_week = date.weekday()
    query = db.query(models.Timetable).options(
        joinedload(models.Timetable.section).joinedload(models.Section.class_),
        joinedload(models.Timetable.subject),
        joinedload(models.Timetable.activity),
        joinedload(models.Timetable.resource),
        joinedload(models.Timetable.teacher).joinedload(models.Teacher.user),
    ).filter(models.Timetable.day_of_week == day_of_week)
    if user.role != models.RoleEnum.super_admin:
        query = query.filter(models.Timetable.school_id == user.school_id)
    if section_id:
        query = query.filter(models.Timetable.section_id == section_id)
    # NOTE: teacher_id is intentionally NOT filtered here at the SQL level.
    # A teacher's *effective* schedule can include a slot whose master
    # Timetable.teacher_id belongs to someone else (they're covering it via
    # an approved Swap or a Substitution — see the "still include it" check
    # below, in the per-slot loop). Filtering by master teacher_id here
    # would silently drop those rows before they're ever loaded, making
    # that later Python-side check unreachable dead code. So filtering by
    # teacher_id is done in Python after the substitution/swap overlays are
    # resolved instead (still cheap: at most one school-day of periods).
    slots = query.all()

    slot_ids = [s.id for s in slots]
    subs = {}
    if slot_ids:
        rows = db.query(models.Substitution).options(
            joinedload(models.Substitution.substitute_teacher).joinedload(models.Teacher.user)
        ).filter(models.Substitution.timetable_id.in_(slot_ids), models.Substitution.date == date).all()
        subs = {r.timetable_id: r for r in rows}

    # Phase 5: approved Swaps for this exact date, keyed by each side's
    # timetable_id -> the *other* side's Timetable row (its counterpart).
    # A Substitution on a slot takes priority over a Swap on that same slot
    # (see swaps.py module docstring for the scope note).
    swap_partner: dict[int, models.Timetable] = {}
    if slot_ids:
        swap_rows = db.query(models.Swap).options(
            joinedload(models.Swap.timetable_a).joinedload(models.Timetable.section).joinedload(models.Section.class_),
            joinedload(models.Swap.timetable_a).joinedload(models.Timetable.subject),
            joinedload(models.Swap.timetable_a).joinedload(models.Timetable.activity),
            joinedload(models.Swap.timetable_a).joinedload(models.Timetable.resource),
            joinedload(models.Swap.timetable_a).joinedload(models.Timetable.teacher).joinedload(models.Teacher.user),
            joinedload(models.Swap.timetable_b).joinedload(models.Timetable.section).joinedload(models.Section.class_),
            joinedload(models.Swap.timetable_b).joinedload(models.Timetable.subject),
            joinedload(models.Swap.timetable_b).joinedload(models.Timetable.activity),
            joinedload(models.Swap.timetable_b).joinedload(models.Timetable.resource),
            joinedload(models.Swap.timetable_b).joinedload(models.Timetable.teacher).joinedload(models.Teacher.user),
        ).filter(
            models.Swap.status == models.SwapStatus.approved,
            models.Swap.date == date,
            (models.Swap.timetable_id_a.in_(slot_ids)) | (models.Swap.timetable_id_b.in_(slot_ids)),
        ).all()
        for sw in swap_rows:
            if sw.timetable_a and sw.timetable_b:
                swap_partner[sw.timetable_id_a] = sw.timetable_b
                swap_partner[sw.timetable_id_b] = sw.timetable_a

    out = []
    for s in slots:
        sub = subs.get(s.id)
        partner = swap_partner.get(s.id) if not sub else None

        if sub:
            kind = "subject" if s.subject_id else ("activity" if s.activity_id else "free")
            teacher_id_eff = sub.substitute_teacher_id
            teacher_name_eff = sub.substitute_teacher.user.name if sub.substitute_teacher else None
            subject_name_eff, activity_name_eff, resource_name_eff = (
                s.subject.name if s.subject else None,
                s.activity.name if s.activity else None,
                s.resource.name if s.resource else None,
            )
        elif partner:
            kind = "subject" if partner.subject_id else ("activity" if partner.activity_id else "free")
            teacher_id_eff = partner.teacher_id
            teacher_name_eff = partner.teacher.user.name if partner.teacher else None
            subject_name_eff, activity_name_eff, resource_name_eff = (
                partner.subject.name if partner.subject else None,
                partner.activity.name if partner.activity else None,
                partner.resource.name if partner.resource else None,
            )
        else:
            kind = "subject" if s.subject_id else ("activity" if s.activity_id else "free")
            teacher_id_eff = s.teacher_id
            teacher_name_eff = s.teacher.user.name if s.teacher else None
            subject_name_eff, activity_name_eff, resource_name_eff = (
                s.subject.name if s.subject else None,
                s.activity.name if s.activity else None,
                s.resource.name if s.resource else None,
            )

        # If teacher_id filter is applied and this teacher only appears via
        # an overlay (not on the master row), still include it.
        if teacher_id and s.teacher_id != teacher_id and teacher_id_eff != teacher_id:
            continue

        out.append(schemas.EffectiveSlotOut(
            timetable_id=s.id,
            day_of_week=s.day_of_week,
            period=s.period,
            section_id=s.section_id,
            section_name=f"{s.section.class_.name} {s.section.name}" if s.section else "",
            kind=kind,
            subject_name=subject_name_eff,
            activity_name=activity_name_eff,
            resource_name=resource_name_eff,
            teacher_id=teacher_id_eff,
            teacher_name=teacher_name_eff,
            is_substituted=sub is not None,
            original_teacher_name=s.teacher.user.name if (sub and s.teacher) else None,
            is_swapped=partner is not None,
            swap_partner_label=(
                f"{partner.section.class_.name} {partner.section.name} P{partner.period}" if partner and partner.section else None
            ),
        ))
    return out
