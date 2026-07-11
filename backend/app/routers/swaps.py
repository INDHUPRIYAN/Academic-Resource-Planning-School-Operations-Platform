"""
Swap Management (Phase 5).

Lets a teacher (or admin, on a teacher's behalf) request that two
master-timetable slots exchange their effective content — subject,
teacher, activity, and resource — for one specific date. Like Substitution
(Phase 4), this is a Layer 2 overlay: the master Timetable rows
(timetable_id_a / timetable_id_b) are never modified. GET
/substitutions/schedule computes the resulting effective schedule for a
given date, overlaying both approved Substitutions and approved Swaps.

Both slots must share the same day_of_week, and that day_of_week must
equal the requested date's weekday — a swap exchanges two periods/classes
happening on the same calendar day, not a move to a different day. This
covers both common cases: the same section reordering two of its own
periods, and two different sections/teachers trading their same-day
classes.

Approval workflow mirrors Leave: pending -> approved/rejected by a school
admin. On approval, each side of the swap is re-validated so neither
teacher (nor resource, if set) ends up double-booked at the position
they're moving into — checked against the master timetable, existing
approved Substitutions, and other approved Swaps for that date. If either
side would conflict, approval is rejected with 409 and the admin must
resolve it manually (no fallback tiers, unlike substitution — a swap is a
voluntary schedule change, not a mandatory coverage requirement).

Scope note: if a slot is targeted by both an approved Substitution and an
approved Swap on the same date (rare — e.g. the teacher who was about to
swap then goes on leave before the swap date), the Substitution overlay
takes priority when computing the effective schedule; the swap's other
side still shows normally. This mirrors the documented department-fallback
scope note from Phase 4: an edge case worth knowing about, not a bug.
"""
from datetime import datetime, date as date_cls

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.auth import get_current_user, require_roles
from app.crud_factory import log_action
from app import models, schemas

router = APIRouter(prefix="/swaps", tags=["swaps"])
ADMIN_ROLES = (models.RoleEnum.super_admin, models.RoleEnum.school_admin,
                models.RoleEnum.principal, models.RoleEnum.vice_principal)


def _with_joins(query):
    return query.options(
        joinedload(models.Swap.timetable_a).joinedload(models.Timetable.section).joinedload(models.Section.class_),
        joinedload(models.Swap.timetable_a).joinedload(models.Timetable.subject),
        joinedload(models.Swap.timetable_a).joinedload(models.Timetable.activity),
        joinedload(models.Swap.timetable_a).joinedload(models.Timetable.teacher).joinedload(models.Teacher.user),
        joinedload(models.Swap.timetable_b).joinedload(models.Timetable.section).joinedload(models.Section.class_),
        joinedload(models.Swap.timetable_b).joinedload(models.Timetable.subject),
        joinedload(models.Swap.timetable_b).joinedload(models.Timetable.activity),
        joinedload(models.Swap.timetable_b).joinedload(models.Timetable.teacher).joinedload(models.Teacher.user),
    )


def _slot_label(slot: models.Timetable | None) -> str:
    if not slot:
        return "(deleted slot)"
    section = f"{slot.section.class_.name} {slot.section.name}" if slot.section else "?"
    what = slot.subject.name if slot.subject else (slot.activity.name if slot.activity else "Free")
    who = f" ({slot.teacher.user.name})" if slot.teacher else ""
    return f"{section} · Day {slot.day_of_week} P{slot.period} · {what}{who}"


def to_swap_out(row: models.Swap, db: Session) -> schemas.SwapOut:
    requester_name = None
    if row.requested_by:
        u = db.query(models.User).filter(models.User.id == row.requested_by).first()
        requester_name = u.name if u else None
    return schemas.SwapOut(
        id=row.id,
        timetable_id_a=row.timetable_id_a,
        timetable_id_b=row.timetable_id_b,
        slot_a_label=_slot_label(row.timetable_a),
        slot_b_label=_slot_label(row.timetable_b),
        date=row.date,
        date_b=row.date_b,
        cross_day=bool(row.date_b and row.date_b != row.date),
        target_accepted=row.target_accepted,
        target_note=row.target_note,
        status=row.status,
        requested_by=row.requested_by,
        requested_by_name=requester_name,
        reason=row.reason,
        decision_note=row.decision_note,
        approved_by=row.approved_by,
        reviewed_by=row.reviewed_by,
        reviewed_at=row.reviewed_at,
        created_at=row.created_at,
    )


def _teacher_id_for(db: Session, user: models.User) -> int | None:
    t = db.query(models.Teacher).filter(models.Teacher.user_id == user.id).first()
    return t.id if t else None


def get_or_404(db: Session, swap_id: int, user: models.User) -> models.Swap:
    row = _with_joins(db.query(models.Swap)).filter(models.Swap.id == swap_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Swap not found")
    if user.role != models.RoleEnum.super_admin and row.school_id != user.school_id:
        raise HTTPException(status_code=403, detail="Swap belongs to a different school")
    if user.role == models.RoleEnum.teacher:
        my_teacher_id = _teacher_id_for(db, user)
        involved = my_teacher_id is not None and (
            row.timetable_a and row.timetable_a.teacher_id == my_teacher_id
            or row.timetable_b and row.timetable_b.teacher_id == my_teacher_id
        )
        if not involved and row.requested_by != user.id:
            raise HTTPException(status_code=403, detail="Not your swap request")
    return row


@router.post("", response_model=schemas.SwapOut, status_code=201)
def request_swap(
    payload: schemas.SwapCreate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    if payload.timetable_id_a == payload.timetable_id_b:
        raise HTTPException(status_code=400, detail="Cannot swap a slot with itself")

    slot_a = db.query(models.Timetable).filter(models.Timetable.id == payload.timetable_id_a).first()
    slot_b = db.query(models.Timetable).filter(models.Timetable.id == payload.timetable_id_b).first()
    if not slot_a or not slot_b:
        raise HTTPException(status_code=404, detail="One or both timetable slots not found")
    if slot_a.school_id != slot_b.school_id:
        raise HTTPException(status_code=400, detail="Both slots must belong to the same school")
    if user.role != models.RoleEnum.super_admin and slot_a.school_id != user.school_id:
        raise HTTPException(status_code=403, detail="These slots belong to a different school")

    # Each slot is exchanged on its OWN date. Same-day swaps leave date_b empty, which
    # keeps every pre-existing swap behaving exactly as before.
    date_a = payload.date
    date_b = payload.date_b
    cross_day = date_b is not None and date_b != date_a

    if cross_day and not _policy(db, slot_a.school_id, "allow_cross_day_swaps", True):
        raise HTTPException(status_code=400,
                            detail="Cross-day swaps are disabled in this school's scheduling policies")
    if slot_a.day_of_week != date_a.weekday():
        raise HTTPException(status_code=400,
                            detail="Slot A's day_of_week must match the weekday of its date")
    eff_b = date_b or date_a
    if slot_b.day_of_week != eff_b.weekday():
        raise HTTPException(
            status_code=400,
            detail="Slot B's day_of_week must match the weekday of its date"
                   + ("" if cross_day else " (for a same-day swap both slots must be on the same weekday)"),
        )

    if user.role == models.RoleEnum.teacher:
        my_teacher_id = _teacher_id_for(db, user)
        if my_teacher_id is None or my_teacher_id not in (slot_a.teacher_id, slot_b.teacher_id):
            raise HTTPException(status_code=403, detail="You can only request a swap involving one of your own classes")

    row = models.Swap(
        timetable_id_a=payload.timetable_id_a,
        timetable_id_b=payload.timetable_id_b,
        date=date_a,
        date_b=date_b,
        school_id=slot_a.school_id,
        status=models.SwapStatus.pending,
        requested_by=user.id,
        reason=payload.reason,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    log_action(db, user.id, "request_swap", f"swap_id={row.id} a={payload.timetable_id_a} b={payload.timetable_id_b}")
    return to_swap_out(get_or_404(db, row.id, user), db)


@router.get("")
def list_swaps(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=500),
    status: models.SwapStatus | None = None,
    date: date_cls | None = None,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    query = _with_joins(db.query(models.Swap))
    if user.role == models.RoleEnum.teacher:
        my_teacher_id = _teacher_id_for(db, user)
        query = query.join(
            models.Timetable,
            (models.Timetable.id == models.Swap.timetable_id_a) | (models.Timetable.id == models.Swap.timetable_id_b),
        ).filter(
            (models.Timetable.teacher_id == (my_teacher_id if my_teacher_id is not None else -1))
            | (models.Swap.requested_by == user.id)
        ).distinct()
    elif user.role != models.RoleEnum.super_admin:
        query = query.filter(models.Swap.school_id == user.school_id)
    if status:
        query = query.filter(models.Swap.status == status)
    if date:
        query = query.filter(models.Swap.date == date)
    total = query.count()
    items = query.order_by(models.Swap.created_at.desc()).offset((page - 1) * limit).limit(limit).all()
    return {"items": [to_swap_out(i, db) for i in items], "total": total, "page": page, "limit": limit}


@router.get("/{swap_id}", response_model=schemas.SwapOut)
def get_swap(swap_id: int, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    return to_swap_out(get_or_404(db, swap_id, user), db)


@router.delete("/{swap_id}", status_code=204)
def cancel_swap(swap_id: int, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    row = get_or_404(db, swap_id, user)
    if row.status != models.SwapStatus.pending:
        raise HTTPException(status_code=400, detail="Only pending swap requests can be cancelled")
    if user.role == models.RoleEnum.teacher and row.requested_by != user.id:
        raise HTTPException(status_code=403, detail="Only the requester (or an admin) can cancel this swap")
    db.delete(row)
    db.commit()
    log_action(db, user.id, "cancel_swap", f"swap_id={swap_id}")


def _absent_on(db: Session, teacher_id: int, on_date, period: int) -> bool:
    """True if the teacher is on approved leave, or on approved on-duty covering this
    period - either way they cannot take on a swapped class then."""
    from app.substitution_engine import _od_covers_period
    for lv in db.query(models.Leave).filter(
        models.Leave.teacher_id == teacher_id,
        models.Leave.status == models.LeaveStatus.approved,
    ):
        if lv.date <= on_date <= (lv.end_date or lv.date):
            return True
    for od in db.query(models.OnDuty).filter(
        models.OnDuty.teacher_id == teacher_id,
        models.OnDuty.status == models.OnDutyStatus.approved,
    ):
        if od.date <= on_date <= (od.end_date or od.date) and _od_covers_period(od, period):
            return True
    return False


def _policy(db: Session, school_id: int, key: str, default):
    """Every swap rule is configuration, never code. Reads
    SchoolConfig.scheduling_policies[key]."""
    import json
    row = db.query(models.SchoolConfig).filter(models.SchoolConfig.school_id == school_id).first()
    if not row:
        return default
    try:
        return json.loads(row.config).get("scheduling_policies", {}).get(key, default)
    except (ValueError, TypeError):
        return default


def _notify(db: Session, user_id: int, message: str):
    db.add(models.Notification(user_id=user_id, message=message))


def _other_master_conflict(db: Session, teacher_id: int | None, resource_id: int | None,
                            day_of_week: int, period: int, exclude_ids: tuple[int, int]) -> str | None:
    """Would placing this teacher/resource at (day_of_week, period) collide
    with a master-timetable slot other than the two being swapped?"""
    if teacher_id:
        hit = db.query(models.Timetable).filter(
            models.Timetable.teacher_id == teacher_id,
            models.Timetable.day_of_week == day_of_week,
            models.Timetable.period == period,
            models.Timetable.id.notin_(exclude_ids),
        ).first()
        if hit:
            return f"teacher is already scheduled elsewhere at that day/period"
    if resource_id:
        hit = db.query(models.Timetable).filter(
            models.Timetable.resource_id == resource_id,
            models.Timetable.day_of_week == day_of_week,
            models.Timetable.period == period,
            models.Timetable.id.notin_(exclude_ids),
        ).first()
        if hit:
            return f"resource is already booked elsewhere at that day/period"
    return None


def _overlay_conflict(db: Session, teacher_id: int | None, on_date, day_of_week: int, period: int,
                       exclude_swap_id: int) -> str | None:
    """Would this teacher already be covering a Substitution, or be one side
    of a different approved Swap, at this exact day/period on this date?"""
    if not teacher_id:
        return None
    sub_hit = (
        db.query(models.Substitution)
        .join(models.Timetable, models.Substitution.timetable_id == models.Timetable.id)
        .filter(
            models.Substitution.substitute_teacher_id == teacher_id,
            models.Substitution.date == on_date,
            models.Timetable.day_of_week == day_of_week,
            models.Timetable.period == period,
        ).first()
    )
    if sub_hit:
        return "teacher is already covering a substitution at that day/period on this date"
    other_swaps = (
        db.query(models.Swap)
        .filter(models.Swap.status == models.SwapStatus.approved, models.Swap.date == on_date,
                models.Swap.id != exclude_swap_id)
        .options(joinedload(models.Swap.timetable_a), joinedload(models.Swap.timetable_b))
        .all()
    )
    for sw in other_swaps:
        for slot in (sw.timetable_a, sw.timetable_b):
            if slot and slot.teacher_id == teacher_id and slot.day_of_week == day_of_week and slot.period == period:
                return "teacher is already involved in another approved swap at that day/period on this date"
    return None


@router.post("/{swap_id}/approve", response_model=schemas.SwapOut)
def approve_swap(
    swap_id: int,
    payload: schemas.SwapDecision,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_roles(*ADMIN_ROLES)),
):
    row = get_or_404(db, swap_id, user)
    if row.status != models.SwapStatus.pending:
        raise HTTPException(status_code=400, detail="Swap has already been reviewed")
    slot_a, slot_b = row.timetable_a, row.timetable_b
    if not slot_a or not slot_b:
        raise HTTPException(status_code=400, detail="One of the swapped slots no longer exists")

    # Two-step consent: the target teacher must agree first (configurable).
    if _policy(db, row.school_id, "swap_requires_teacher_approval", True):
        if row.target_accepted is None:
            raise HTTPException(status_code=409,
                                detail="The target teacher has not accepted this swap yet")
        if row.target_accepted is False:
            raise HTTPException(status_code=409, detail="The target teacher declined this swap")

    date_a = row.date
    date_b = row.date_b or row.date

    exclude = (slot_a.id, slot_b.id)
    # Teacher A moves into slot B's day/period ON DATE B; teacher B moves into slot A's
    # day/period ON DATE A. For a same-day swap both dates are the same, so this is
    # identical to the previous behaviour.
    for label, moving_teacher_id, moving_resource_id, target_day, target_period, on_date in (
        ("A", slot_a.teacher_id, slot_a.resource_id, slot_b.day_of_week, slot_b.period, date_b),
        ("B", slot_b.teacher_id, slot_b.resource_id, slot_a.day_of_week, slot_a.period, date_a),
    ):
        conflict = _other_master_conflict(db, moving_teacher_id, moving_resource_id, target_day, target_period, exclude)
        if conflict:
            raise HTTPException(status_code=409, detail=f"Cannot approve: slot {label}'s {conflict}")
        conflict = _overlay_conflict(db, moving_teacher_id, on_date, target_day, target_period, row.id)
        if conflict:
            raise HTTPException(status_code=409, detail=f"Cannot approve: slot {label}'s {conflict}")
        # A teacher on approved leave / on-duty cannot pick up a swapped period.
        if moving_teacher_id and _absent_on(db, moving_teacher_id, on_date, target_period):
            raise HTTPException(
                status_code=409,
                detail=f"Cannot approve: slot {label}'s teacher is on approved leave or on-duty "
                       f"on {on_date} period {target_period}",
            )

    row.status = models.SwapStatus.approved
    row.decision_note = payload.note
    row.approved_by = user.id
    row.reviewed_by = user.id
    row.reviewed_at = datetime.utcnow()

    a_label, b_label = _slot_label(slot_a), _slot_label(slot_b)
    if slot_a.teacher and slot_a.teacher.user_id != user.id:
        _notify(db, slot_a.teacher.user_id, f"Your {row.date} class is being swapped: {a_label} ⇄ {b_label}.")
    if slot_b.teacher and slot_b.teacher.user_id != user.id and slot_b.teacher_id != slot_a.teacher_id:
        _notify(db, slot_b.teacher.user_id, f"Your {row.date} class is being swapped: {b_label} ⇄ {a_label}.")
    if row.requested_by and row.requested_by != user.id and row.requested_by not in (
        slot_a.teacher.user_id if slot_a.teacher else None, slot_b.teacher.user_id if slot_b.teacher else None,
    ):
        _notify(db, row.requested_by, f"Your swap request for {row.date} was approved.")

    db.commit()
    db.refresh(row)
    log_action(db, user.id, "approve_swap", f"swap_id={swap_id}")
    return to_swap_out(get_or_404(db, swap_id, user), db)


@router.post("/{swap_id}/reject", response_model=schemas.SwapOut)
def reject_swap(
    swap_id: int,
    payload: schemas.SwapDecision,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_roles(*ADMIN_ROLES)),
):
    row = get_or_404(db, swap_id, user)
    if row.status != models.SwapStatus.pending:
        raise HTTPException(status_code=400, detail="Swap has already been reviewed")
    row.status = models.SwapStatus.rejected
    row.decision_note = payload.note
    row.reviewed_by = user.id
    row.reviewed_at = datetime.utcnow()
    if row.requested_by:
        _notify(db, row.requested_by, f"Your swap request for {row.date} was rejected."
                + (f" Note: {payload.note}" if payload.note else ""))
    db.commit()
    db.refresh(row)
    log_action(db, user.id, "reject_swap", f"swap_id={swap_id}")
    return to_swap_out(get_or_404(db, swap_id, user), db)


# ---------------------------------------------------------------------------
# Two-step consent: the TARGET teacher answers first, then an admin/principal
# approves. Configurable via scheduling_policies.swap_requires_teacher_approval.
# ---------------------------------------------------------------------------
def _target_teacher_id(db: Session, row: models.Swap, user: models.User) -> int | None:
    """The teacher on the OTHER side from the requester."""
    slot_a, slot_b = row.timetable_a, row.timetable_b
    if not slot_a or not slot_b:
        return None
    requester_teacher = db.query(models.Teacher).filter(
        models.Teacher.user_id == row.requested_by).first()
    rid = requester_teacher.id if requester_teacher else None
    if rid == slot_a.teacher_id:
        return slot_b.teacher_id
    if rid == slot_b.teacher_id:
        return slot_a.teacher_id
    return None  # raised by an admin on behalf of both sides


@router.post("/{swap_id}/target-accept", response_model=schemas.SwapOut)
def target_accept(
    swap_id: int,
    payload: schemas.SwapDecision,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """The target teacher agrees to take the exchange. It still needs admin approval."""
    row = get_or_404(db, swap_id, user)
    if row.status != models.SwapStatus.pending:
        raise HTTPException(status_code=400, detail="Swap has already been reviewed")

    target_id = _target_teacher_id(db, row, user)
    me = _teacher_id_for(db, user)
    if user.role == models.RoleEnum.teacher and (target_id is None or me != target_id):
        raise HTTPException(status_code=403, detail="You are not the target teacher for this swap")

    row.target_accepted = True
    row.target_note = payload.note
    row.target_reviewed_at = datetime.utcnow()
    if row.requested_by:
        _notify(db, row.requested_by,
                f"Your swap request #{row.id} was accepted by the other teacher. Awaiting admin approval.")
    db.commit()
    db.refresh(row)
    log_action(db, user.id, "swap_target_accept", f"swap_id={swap_id}")
    return to_swap_out(get_or_404(db, swap_id, user), db)


@router.post("/{swap_id}/target-reject", response_model=schemas.SwapOut)
def target_reject(
    swap_id: int,
    payload: schemas.SwapDecision,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """The target teacher declines - the swap is rejected outright."""
    row = get_or_404(db, swap_id, user)
    if row.status != models.SwapStatus.pending:
        raise HTTPException(status_code=400, detail="Swap has already been reviewed")

    target_id = _target_teacher_id(db, row, user)
    me = _teacher_id_for(db, user)
    if user.role == models.RoleEnum.teacher and (target_id is None or me != target_id):
        raise HTTPException(status_code=403, detail="You are not the target teacher for this swap")

    row.target_accepted = False
    row.target_note = payload.note
    row.target_reviewed_at = datetime.utcnow()
    row.status = models.SwapStatus.rejected
    row.decision_note = f"Declined by the target teacher. {payload.note or ''}".strip()
    if row.requested_by:
        _notify(db, row.requested_by,
                f"Your swap request #{row.id} was declined by the other teacher."
                + (f" Note: {payload.note}" if payload.note else ""))
    db.commit()
    db.refresh(row)
    log_action(db, user.id, "swap_target_reject", f"swap_id={swap_id}")
    return to_swap_out(get_or_404(db, swap_id, user), db)
