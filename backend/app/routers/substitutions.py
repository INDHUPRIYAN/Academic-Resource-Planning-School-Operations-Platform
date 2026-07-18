from datetime import date as date_cls

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.auth import get_current_user, require_roles
from app.crud_factory import log_action
from app.substitution_engine import _is_free
from app import models, schemas

router = APIRouter(prefix="/substitutions", tags=["substitutions"])
ADMIN_ROLES = (models.RoleEnum.super_admin, models.RoleEnum.school_admin,
                models.RoleEnum.principal, models.RoleEnum.vice_principal)


def _with_joins_tt(db: Session):
    """Timetable rows with everything needed to label a slot."""
    return db.query(models.Timetable).options(
        joinedload(models.Timetable.section).joinedload(models.Section.class_),
        joinedload(models.Timetable.subject),
        joinedload(models.Timetable.activity),
        joinedload(models.Timetable.teacher).joinedload(models.Teacher.user),
    )


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
        on_duty_id=row.on_duty_id,
        timetable_id=row.timetable_id,
        substitute_teacher_id=row.substitute_teacher_id,
        substitute_teacher_name=row.substitute_teacher.user.name if row.substitute_teacher else "",
        original_teacher_name=tt.teacher.user.name if tt and tt.teacher else "",
        date=row.date,
        method=row.method,
        reason=row.reason,
        assigned_by=row.assigned_by,
        rank=row.rank,
        score=row.score,
        decline_reason=row.decline_reason,
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
            # Cross-day: side A is exchanged on `date`, side B on `date_b`. A NULL
            # date_b means "same day as A", which is how every same-day swap behaves.
            (models.Swap.date == date) | (func.coalesce(models.Swap.date_b, models.Swap.date) == date),
            (models.Swap.timetable_id_a.in_(slot_ids)) | (models.Swap.timetable_id_b.in_(slot_ids)),
        ).all()
        for sw in swap_rows:
            if not (sw.timetable_a and sw.timetable_b):
                continue
            # Each side only flips on ITS OWN date. For a same-day swap both branches
            # fire, reproducing the original a<->b behaviour exactly.
            if sw.date == date:
                swap_partner[sw.timetable_id_a] = sw.timetable_b
            if (sw.date_b or sw.date) == date:
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


# ---------------------------------------------------------------------------
# Ranked substitute queue
# ---------------------------------------------------------------------------
# The engine never picks a single teacher and stops: it scores EVERY eligible
# teacher and stores the ranked list. Rank 1 serves; the rest wait as backups.
# The queue is readable by every teacher - substitution duty is transparent.

# Declining because "it is my free period" is explicitly not acceptable: free
# periods belong to the institution. Only concrete reasons are accepted.
_INVALID_DECLINE = ("free period", "free-period", "my free", "not my duty",
                    "i am free", "im free", "no reason")


@router.get("/candidates", response_model=schemas.SubstituteQueueOut)
def substitute_candidates(
    timetable_id: int = Query(..., description="The master-timetable slot (the hour) to cover"),
    date: date_cls = Query(..., description="The calendar date to cover it on"),
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """WHO CAN COVER THIS HOUR? — the full ranked list of every teacher eligible to
    substitute for one slot on one date.

    This is a read-only preview: nothing is created or assigned. It works whether or
    not a leave/on-duty exists yet, so an admin can see the options *before* deciding,
    and any teacher can see who is in line. Ordering and scores are exactly what the
    engine would use to auto-assign (rank 1 is who it would pick).
    """
    from app.services.substitute_queue import queue_for
    from app.substitution_engine import rank_substitutes

    slot = _with_joins_tt(db).filter(models.Timetable.id == timetable_id).first()
    if not slot:
        raise HTTPException(status_code=404, detail="Timetable slot not found")
    if user.role != models.RoleEnum.super_admin and slot.school_id != user.school_id:
        raise HTTPException(status_code=403, detail="That slot belongs to a different school")
    if slot.day_of_week != date.weekday():
        raise HTTPException(
            status_code=400,
            detail=f"That slot is taught on day_of_week {slot.day_of_week}, but {date} is a "
                   f"different weekday. Pick a date whose weekday matches the slot.",
        )

    # If a cover already exists, show the REAL stored queue (with declines); otherwise
    # compute a live preview.
    existing = db.query(models.Substitution).filter(
        models.Substitution.timetable_id == timetable_id,
        models.Substitution.date == date,
    ).first()

    if existing:
        rows = queue_for(db, timetable_id, date)
        cands = [
            schemas.SubstituteCandidateOut(
                teacher_id=c.teacher_id,
                teacher_name=c.teacher.user.name if c.teacher and c.teacher.user else "",
                rank=c.rank, score=c.score, method=c.method, reason=c.reason,
                status=c.status.value, decline_reason=c.decline_reason,
            ) for c in rows
        ]
        assigned = (existing.substitute_teacher.user.name
                    if existing.substitute_teacher and existing.substitute_teacher.user else None)
        sub_id = existing.id
    else:
        ranked = rank_substitutes(db, slot, date, slot.teacher_id or -1)
        cands = [
            schemas.SubstituteCandidateOut(
                teacher_id=rc.teacher_id, teacher_name=rc.teacher_name, rank=rc.rank,
                score=rc.score, method=rc.method, reason=rc.reason,
                status="eligible", decline_reason=None,
            ) for rc in ranked
        ]
        assigned = None
        sub_id = None

    return schemas.SubstituteQueueOut(
        substitution_id=sub_id,
        timetable_id=slot.id,
        date=date,
        period=slot.period,
        section_name=f"{slot.section.class_.name} {slot.section.name}" if slot.section else "",
        subject_name=slot.subject.name if slot.subject else None,
        assigned_teacher=assigned,
        candidates=cands,
    )


@router.get("/{sub_id}/queue", response_model=schemas.SubstituteQueueOut)
def substitution_queue(
    sub_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """Show the full ranked queue behind one assignment. Visible to ALL teachers."""
    from app.services.substitute_queue import queue_for

    sub = _with_joins(db.query(models.Substitution)).filter(models.Substitution.id == sub_id).first()
    if not sub:
        raise HTTPException(status_code=404, detail="Substitution not found")
    slot = sub.timetable
    rows = queue_for(db, sub.timetable_id, sub.date)
    return schemas.SubstituteQueueOut(
        substitution_id=sub.id,
        timetable_id=sub.timetable_id,
        date=sub.date,
        period=slot.period if slot else 0,
        section_name=(f"{slot.section.class_.name} {slot.section.name}"
                      if slot and slot.section else ""),
        subject_name=slot.subject.name if slot and slot.subject else None,
        assigned_teacher=(sub.substitute_teacher.user.name
                          if sub.substitute_teacher and sub.substitute_teacher.user else None),
        candidates=[
            schemas.SubstituteCandidateOut(
                teacher_id=c.teacher_id,
                teacher_name=c.teacher.user.name if c.teacher and c.teacher.user else "",
                rank=c.rank, score=c.score, method=c.method, reason=c.reason,
                status=c.status.value, decline_reason=c.decline_reason,
            ) for c in rows
        ],
    )


@router.post("/{sub_id}/decline", response_model=schemas.SubstitutionOut)
def decline_substitution(
    sub_id: int,
    payload: schemas.SubstituteDecline,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """The ASSIGNED substitute steps aside with a valid reason; the next backup in the
    ranked queue is promoted automatically (no admin round-trip, no re-solve)."""
    from app.services.substitute_queue import promote_next

    sub = _with_joins(db.query(models.Substitution)).filter(models.Substitution.id == sub_id).first()
    if not sub:
        raise HTTPException(status_code=404, detail="Substitution not found")

    # Only the assigned teacher may decline (an admin uses the manual-override route).
    me = db.query(models.Teacher).filter(models.Teacher.user_id == user.id).first()
    if user.role == models.RoleEnum.teacher:
        if not me or me.id != sub.substitute_teacher_id:
            raise HTTPException(status_code=403, detail="This substitution is not assigned to you")
    elif user.role not in ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    reason = payload.reason.strip()
    if any(bad in reason.lower() for bad in _INVALID_DECLINE):
        raise HTTPException(
            status_code=400,
            detail="A free period is not a valid reason to decline - free periods belong to "
                   "the institution. Please give a concrete reason (e.g. exam duty, medical, "
                   "official assignment).",
        )

    previous = sub.substitute_teacher.user.name if sub.substitute_teacher and sub.substitute_teacher.user else "Someone"
    new_sub, message = promote_next(db, sub, reason)

    if new_sub is None:
        db.commit()
        log_action(db, user.id, "decline_substitution", f"sub_id={sub_id} uncovered=1")
        raise HTTPException(status_code=409, detail=f"{previous} declined. {message}")

    # notify the promoted teacher + the class teacher trail
    promoted = db.query(models.Teacher).options(joinedload(models.Teacher.user)).filter(
        models.Teacher.id == new_sub.substitute_teacher_id).first()
    slot = new_sub.timetable
    label = f"{slot.section.class_.name} {slot.section.name}" if slot and slot.section else "a class"
    if promoted and promoted.user:
        db.add(models.Notification(
            user_id=promoted.user_id,
            message=f"You've been assigned as a substitute (promoted from the backup queue): "
                    f"{new_sub.date} period {slot.period if slot else '?'} ({label}).",
        ))
    db.commit()
    db.refresh(new_sub)
    log_action(db, user.id, "decline_substitution",
               f"sub_id={sub_id} declined_by={previous} promoted_to={new_sub.substitute_teacher_id}")
    return to_sub_out(_with_joins(db.query(models.Substitution)).filter(
        models.Substitution.id == new_sub.id).first())
