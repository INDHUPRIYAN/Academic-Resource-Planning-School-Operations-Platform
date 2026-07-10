from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.auth import get_current_user, require_roles
from app.crud_factory import log_action
from app.services.timetable_generator import generate_master_timetable, TimetableGenerationError
from app.services.timetable_verifier import Slot as VerifierSlot, verify as verify_timetable
from app import models, schemas

router = APIRouter(prefix="/timetables", tags=["timetable"])
ADMIN_ROLES = (models.RoleEnum.super_admin, models.RoleEnum.school_admin)


def scoped(query, user):
    if user.role != models.RoleEnum.super_admin:
        query = query.filter(models.Timetable.school_id == user.school_id)
    return query


def get_or_404(db: Session, timetable_id: int, user) -> models.Timetable:
    row = scoped(db.query(models.Timetable), user).filter(models.Timetable.id == timetable_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Timetable slot not found")
    return row


def assert_school_in_scope(user, school_id: int):
    if user.role != models.RoleEnum.super_admin and school_id != user.school_id:
        raise HTTPException(status_code=403, detail="Cannot act on a different school's data")


def to_slot_out(row: models.Timetable) -> schemas.TimetableSlotOut:
    kind = "subject" if row.subject_id else ("activity" if row.activity_id else "free")
    return schemas.TimetableSlotOut(
        id=row.id,
        section_id=row.section_id,
        section_name=f"{row.section.class_.name} {row.section.name}" if row.section else "",
        day_of_week=row.day_of_week,
        period=row.period,
        is_locked=row.is_locked,
        kind=kind,
        subject_id=row.subject_id,
        subject_name=row.subject.name if row.subject else None,
        teacher_id=row.teacher_id,
        teacher_name=row.teacher.user.name if row.teacher else None,
        activity_id=row.activity_id,
        activity_name=row.activity.name if row.activity else None,
        resource_id=row.resource_id,
        resource_name=row.resource.name if row.resource else None,
    )


def _with_joins(query):
    return query.options(
        joinedload(models.Timetable.section).joinedload(models.Section.class_),
        joinedload(models.Timetable.subject),
        joinedload(models.Timetable.teacher).joinedload(models.Teacher.user),
        joinedload(models.Timetable.activity),
        joinedload(models.Timetable.resource),
    )


@router.post("/generate", response_model=schemas.TimetableGenerateResponse)
def generate_timetable(
    payload: schemas.TimetableGenerateRequest,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_roles(*ADMIN_ROLES)),
):
    if user.role == models.RoleEnum.school_admin:
        school_id = user.school_id
    else:
        if not payload.school_id:
            raise HTTPException(status_code=400, detail="school_id is required for super_admin")
        school_id = payload.school_id

    try:
        result = generate_master_timetable(db, school_id, time_limit_seconds=payload.time_limit_seconds)
    except TimetableGenerationError as e:
        raise HTTPException(status_code=422, detail=str(e))

    # Rule 21 - Final Verification. An independent checker re-derives every hard constraint
    # from the proposed rows (solver output + existing locked rows). Nothing is written
    # unless it passes, so a solver bug can never persist an invalid timetable.
    locked_rows = db.query(models.Timetable).filter(
        models.Timetable.school_id == school_id,
        models.Timetable.is_locked.is_(True),
    ).all()
    proposed = [
        VerifierSlot(section_id=s.section_id, day_of_week=s.day_of_week, period=s.period,
                     subject_id=s.subject_id, activity_id=s.activity_id,
                     teacher_id=s.teacher_id, resource_id=s.resource_id)
        for s in result.slots
    ] + [
        VerifierSlot(section_id=r.section_id, day_of_week=r.day_of_week, period=r.period,
                     subject_id=r.subject_id, activity_id=r.activity_id,
                     teacher_id=r.teacher_id, resource_id=r.resource_id)
        for r in locked_rows
    ]
    report = verify_timetable(db, school_id, proposed)
    if not report.passed:
        db.rollback()
        failed = sorted({v["rule"] for v in report.violations})
        raise HTTPException(status_code=422, detail={
            "message": "Generated timetable failed final verification and was rejected. "
                       "Nothing was saved.",
            "failed_rules": failed,
            "violations": report.violations[:25],
            "total_violations": len(report.violations),
        })

    # Replace only unlocked rows for this school; locked rows are left untouched.
    db.query(models.Timetable).filter(
        models.Timetable.school_id == school_id,
        models.Timetable.is_locked.is_(False),
    ).delete(synchronize_session=False)

    for slot in result.slots:
        db.add(models.Timetable(
            school_id=school_id,
            section_id=slot.section_id,
            subject_id=slot.subject_id,
            teacher_id=slot.teacher_id,
            activity_id=slot.activity_id,
            resource_id=slot.resource_id,
            day_of_week=slot.day_of_week,
            period=slot.period,
            is_locked=False,
        ))
    db.commit()
    log_action(db, user.id, "generate_timetable", f"school_id={school_id} slots={len(result.slots)}")

    return schemas.TimetableGenerateResponse(
        school_id=school_id,
        slots_created=len(result.slots),
        sections_scheduled=result.sections_scheduled,
        optimal=result.optimal,
        verification=report.as_dict(),
        message="Timetable generated." if result.optimal else
                "Timetable generated (feasible solution found within the time limit; may not be fully optimal).",
    )


@router.get("")
def list_timetable(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    section_id: int | None = None,
    teacher_id: int | None = None,
    day_of_week: int | None = None,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    query = _with_joins(scoped(db.query(models.Timetable), user))
    if section_id:
        query = query.filter(models.Timetable.section_id == section_id)
    if teacher_id:
        query = query.filter(models.Timetable.teacher_id == teacher_id)
    if day_of_week is not None:
        query = query.filter(models.Timetable.day_of_week == day_of_week)
    total = query.count()
    items = query.order_by(models.Timetable.day_of_week, models.Timetable.period).offset((page - 1) * limit).limit(limit).all()
    return {
        "items": [to_slot_out(i) for i in items],
        "total": total,
        "page": page,
        "limit": limit,
    }


@router.get("/section/{section_id}")
def get_section_grid(
    section_id: int,
    version_id: int | None = Query(None),
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    section = db.query(models.Section).options(joinedload(models.Section.class_)).filter(models.Section.id == section_id).first()
    if not section:
        raise HTTPException(status_code=404, detail="Section not found")
    if user.role != models.RoleEnum.super_admin and section.class_.school_id != user.school_id:
        raise HTTPException(status_code=403, detail="Section belongs to a different school")

    if version_id:
        rows = (
            db.query(models.TimetableVersionSlot)
            .options(
                joinedload(models.TimetableVersionSlot.section).joinedload(models.Section.class_),
                joinedload(models.TimetableVersionSlot.subject),
                joinedload(models.TimetableVersionSlot.teacher).joinedload(models.Teacher.user),
                joinedload(models.TimetableVersionSlot.activity),
                joinedload(models.TimetableVersionSlot.resource),
            )
            .filter(
                models.TimetableVersionSlot.version_id == version_id,
                models.TimetableVersionSlot.section_id == section_id
            )
            .all()
        )
    else:
        rows = _with_joins(db.query(models.Timetable)).filter(models.Timetable.section_id == section_id).all()
    return {"section_id": section_id, "slots": [to_slot_out(r) for r in rows]}


@router.get("/teacher/{teacher_id}")
def get_teacher_grid(
    teacher_id: int,
    version_id: int | None = Query(None),
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    teacher = db.query(models.Teacher).filter(models.Teacher.id == teacher_id).first()
    if not teacher:
        raise HTTPException(status_code=404, detail="Teacher not found")
    if user.role != models.RoleEnum.super_admin and teacher.school_id != user.school_id:
        raise HTTPException(status_code=403, detail="Teacher belongs to a different school")

    if version_id:
        rows = (
            db.query(models.TimetableVersionSlot)
            .options(
                joinedload(models.TimetableVersionSlot.section).joinedload(models.Section.class_),
                joinedload(models.TimetableVersionSlot.subject),
                joinedload(models.TimetableVersionSlot.teacher).joinedload(models.Teacher.user),
                joinedload(models.TimetableVersionSlot.activity),
                joinedload(models.TimetableVersionSlot.resource),
            )
            .filter(
                models.TimetableVersionSlot.version_id == version_id,
                models.TimetableVersionSlot.teacher_id == teacher_id
            )
            .all()
        )
    else:
        rows = _with_joins(db.query(models.Timetable)).filter(models.Timetable.teacher_id == teacher_id).all()
    return {"teacher_id": teacher_id, "slots": [to_slot_out(r) for r in rows]}


@router.patch("/{timetable_id}/lock", response_model=schemas.TimetableSlotOut)
def toggle_lock(
    timetable_id: int,
    locked: bool = Query(...),
    db: Session = Depends(get_db),
    user: models.User = Depends(require_roles(*ADMIN_ROLES)),
):
    row = get_or_404(db, timetable_id, user)
    row.is_locked = locked
    db.commit()
    db.refresh(row)
    log_action(db, user.id, "lock_timetable_slot" if locked else "unlock_timetable_slot", f"id={row.id}")
    return to_slot_out(_with_joins(db.query(models.Timetable)).filter(models.Timetable.id == row.id).first())


@router.put("/{timetable_id}", response_model=schemas.TimetableSlotOut)
def update_slot(
    timetable_id: int,
    payload: schemas.TimetableSlotUpdate,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_roles(*ADMIN_ROLES)),
):
    """Manual admin override of a single slot (e.g. swapping a teacher or
    moving a lesson). Validates that the new (day, period) doesn't clash with
    another slot for the same section, teacher, or resource."""
    row = get_or_404(db, timetable_id, user)
    data = payload.model_dump(exclude_unset=True)

    new_day = data.get("day_of_week", row.day_of_week)
    new_period = data.get("period", row.period)
    new_teacher_id = data.get("teacher_id", row.teacher_id)
    new_resource_id = data.get("resource_id", row.resource_id)

    conflict_q = db.query(models.Timetable).filter(
        models.Timetable.id != row.id,
        models.Timetable.day_of_week == new_day,
        models.Timetable.period == new_period,
    )
    if conflict_q.filter(models.Timetable.section_id == row.section_id).first():
        raise HTTPException(status_code=409, detail="That section already has a slot at this day/period")
    if new_teacher_id and conflict_q.filter(models.Timetable.teacher_id == new_teacher_id).first():
        raise HTTPException(status_code=409, detail="That teacher is already booked at this day/period")
    if new_resource_id and conflict_q.filter(models.Timetable.resource_id == new_resource_id).first():
        raise HTTPException(status_code=409, detail="That resource is already booked at this day/period")

    for k, v in data.items():
        setattr(row, k, v)
    db.commit()
    db.refresh(row)
    log_action(db, user.id, "update_timetable_slot", f"id={row.id}")
    return to_slot_out(_with_joins(db.query(models.Timetable)).filter(models.Timetable.id == row.id).first())


def _resolve_school_id(user, payload_sid: int | None) -> int:
    if user.role == models.RoleEnum.school_admin:
        return user.school_id
    if not payload_sid:
        raise HTTPException(status_code=400, detail="school_id is required for super_admin")
    return payload_sid


def to_version_out(v: models.TimetableVersion) -> schemas.TimetableVersionOut:
    return schemas.TimetableVersionOut(
        id=v.id,
        school_id=v.school_id,
        name=v.name,
        status=v.status,
        created_at=v.created_at,
        created_by_id=v.created_by_id,
        created_by_name=v.created_by.name if v.created_by else None,
        published_by_id=v.published_by_id,
        published_by_name=v.published_by.name if v.published_by else None,
        published_time=v.published_time,
        reason=v.reason,
        generation_policy=v.generation_policy,
        academic_year=v.academic_year,
        term=v.term,
        semester=v.semester,
    )


@router.get("/versions", response_model=list[schemas.TimetableVersionOut])
def list_versions(
    school_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_roles(*ADMIN_ROLES)),
):
    assert_school_in_scope(user, school_id)
    versions = db.query(models.TimetableVersion).options(
        joinedload(models.TimetableVersion.created_by),
        joinedload(models.TimetableVersion.published_by)
    ).filter(models.TimetableVersion.school_id == school_id).order_by(models.TimetableVersion.created_at.desc()).all()
    return [to_version_out(v) for v in versions]


@router.post("/versions/save-draft", response_model=schemas.TimetableVersionOut)
def save_draft_version(
    payload: schemas.TimetableVersionCreate,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_roles(*ADMIN_ROLES)),
):
    school_id = _resolve_school_id(user, payload.school_id)
    
    # 1. Create version row
    ver = models.TimetableVersion(
        school_id=school_id,
        name=payload.name,
        status="draft",
        created_by_id=user.id,
        reason=payload.reason,
        generation_policy=payload.generation_policy,
        academic_year=payload.academic_year,
        term=payload.term,
        semester=payload.semester
    )
    db.add(ver)
    db.commit()
    db.refresh(ver)

    # 2. Copy current active slots to this version
    active_slots = db.query(models.Timetable).filter(models.Timetable.school_id == school_id).all()
    for s in active_slots:
        v_slot = models.TimetableVersionSlot(
            version_id=ver.id,
            section_id=s.section_id,
            subject_id=s.subject_id,
            teacher_id=s.teacher_id,
            activity_id=s.activity_id,
            resource_id=s.resource_id,
            day_of_week=s.day_of_week,
            period=s.period,
            is_locked=s.is_locked
        )
        db.add(v_slot)
    db.commit()
    log_action(db, user.id, "save_draft_version", f"school_id={school_id} version_id={ver.id}")
    
    # Eager-load relations for schemas
    db.refresh(ver)
    return to_version_out(ver)


@router.post("/versions/{version_id}/submit-review", response_model=schemas.TimetableVersionOut)
def submit_version_for_review(
    version_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_roles(*ADMIN_ROLES)),
):
    ver = db.query(models.TimetableVersion).filter(models.TimetableVersion.id == version_id).first()
    if not ver:
        raise HTTPException(status_code=404, detail="Version not found")
    assert_school_in_scope(user, ver.school_id)

    ver.status = "under_review"
    db.commit()
    log_action(db, user.id, "submit_review_version", f"version_id={version_id}")
    return to_version_out(ver)


@router.post("/versions/{version_id}/approve", response_model=schemas.TimetableVersionOut)
def approve_version(
    version_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_roles(*ADMIN_ROLES)),
):
    ver = db.query(models.TimetableVersion).filter(models.TimetableVersion.id == version_id).first()
    if not ver:
        raise HTTPException(status_code=404, detail="Version not found")
    assert_school_in_scope(user, ver.school_id)

    ver.status = "approved"
    db.commit()
    log_action(db, user.id, "approve_version", f"version_id={version_id}")
    return to_version_out(ver)


@router.post("/versions/{version_id}/publish")
def publish_version(
    version_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_roles(*ADMIN_ROLES)),
):
    ver = db.query(models.TimetableVersion).filter(models.TimetableVersion.id == version_id).first()
    if not ver:
        raise HTTPException(status_code=404, detail="Version not found")
    assert_school_in_scope(user, ver.school_id)

    # 1. Validation Before Publish (Item 8)
    from app.services.validation_engine import validation_registry
    report = validation_registry.validate(ver.school_id, db, bypass_cache=True)
    if not report.get("ready_to_publish", True):
        # Gather blocker messages
        blockers = []
        for cat in report.get("categories", {}).values():
            for item in cat.get("items", []):
                if item.get("severity") == "Critical Error":
                    blockers.append(item.get("message"))
        raise HTTPException(
            status_code=400,
            detail=f"Publish blocked due to low readiness score ({report.get('readiness_score')}%). Blocker errors: {'; '.join(blockers)}"
        )

    # Archive any previously published versions
    db.query(models.TimetableVersion).filter(
        models.TimetableVersion.school_id == ver.school_id,
        models.TimetableVersion.status == "published"
    ).update({"status": "archived"}, synchronize_session=False)

    # Overwrite active timetable with slots from version
    db.query(models.Timetable).filter(models.Timetable.school_id == ver.school_id).delete(synchronize_session=False)

    for vs in ver.slots:
        db.add(models.Timetable(
            school_id=ver.school_id,
            section_id=vs.section_id,
            subject_id=vs.subject_id,
            teacher_id=vs.teacher_id,
            activity_id=vs.activity_id,
            resource_id=vs.resource_id,
            day_of_week=vs.day_of_week,
            period=vs.period,
            is_locked=vs.is_locked
        ))
    
    from datetime import datetime as dt_now
    ver.status = "published"
    ver.published_by_id = user.id
    ver.published_time = dt_now.utcnow()
    db.commit()
    log_action(db, user.id, "publish_version", f"version_id={version_id}")
    return {"message": f"Version '{ver.name}' published successfully."}


@router.post("/versions/{version_id}/rollback")
def rollback_version(
    version_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_roles(*ADMIN_ROLES)),
):
    ver = db.query(models.TimetableVersion).filter(models.TimetableVersion.id == version_id).first()
    if not ver:
        raise HTTPException(status_code=404, detail="Version not found")
    assert_school_in_scope(user, ver.school_id)

    db.query(models.Timetable).filter(models.Timetable.school_id == ver.school_id).delete(synchronize_session=False)

    for vs in ver.slots:
        db.add(models.Timetable(
            school_id=ver.school_id,
            section_id=vs.section_id,
            subject_id=vs.subject_id,
            teacher_id=vs.teacher_id,
            activity_id=vs.activity_id,
            resource_id=vs.resource_id,
            day_of_week=vs.day_of_week,
            period=vs.period,
            is_locked=vs.is_locked
        ))
    
    db.commit()
    log_action(db, user.id, "rollback_version", f"version_id={version_id}")
    return {"message": f"Rollback to version '{ver.name}' completed successfully."}


@router.post("/versions/{version_id}/compare", response_model=schemas.TimetableVersionCompareResponse)
def compare_version(
    version_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_roles(*ADMIN_ROLES)),
):
    ver = db.query(models.TimetableVersion).options(joinedload(models.TimetableVersion.slots)).filter(models.TimetableVersion.id == version_id).first()
    if not ver:
        raise HTTPException(status_code=404, detail="Version not found")
    assert_school_in_scope(user, ver.school_id)

    active_slots = db.query(models.Timetable).options(
        joinedload(models.Timetable.section).joinedload(models.Section.class_),
        joinedload(models.Timetable.subject),
        joinedload(models.Timetable.teacher).joinedload(models.Teacher.user),
        joinedload(models.Timetable.activity),
        joinedload(models.Timetable.resource)
    ).filter(models.Timetable.school_id == ver.school_id).all()

    active_map = {(s.section_id, s.day_of_week, s.period): s for s in active_slots}
    diffs = []

    ver_slots = db.query(models.TimetableVersionSlot).options(
        joinedload(models.TimetableVersionSlot.section).joinedload(models.Section.class_),
        joinedload(models.TimetableVersionSlot.subject),
        joinedload(models.TimetableVersionSlot.teacher).joinedload(models.Teacher.user),
        joinedload(models.TimetableVersionSlot.activity),
        joinedload(models.TimetableVersionSlot.resource)
    ).filter(models.TimetableVersionSlot.version_id == version_id).all()
    ver_map = {(s.section_id, s.day_of_week, s.period): s for s in ver_slots}

    all_keys = set(active_map.keys()).union(ver_map.keys())

    for key in all_keys:
        act = active_map.get(key)
        vsl = ver_map.get(key)
        
        def details_str(s):
            if not s:
                return "Free"
            if s.subject:
                t_name = s.teacher.user.name if s.teacher else "No teacher"
                r_name = f" [{s.resource.name}]" if s.resource else ""
                return f"{s.subject.name} ({t_name}){r_name}"
            if s.activity:
                r_name = f" [{s.resource.name}]" if s.resource else ""
                return f"Activity: {s.activity.name}{r_name}"
            return "Free"

        act_det = details_str(act)
        vsl_det = details_str(vsl)

        if act_det != vsl_det:
            sec_obj = act.section if act else vsl.section
            sec_name = f"{sec_obj.class_.name} {sec_obj.name}" if sec_obj else "Unknown Section"
            diffs.append(schemas.TimetableVersionCompareSlot(
                day_of_week=key[1],
                period=key[2],
                section_name=sec_name,
                active_details=act_det,
                version_details=vsl_det
            ))

    return schemas.TimetableVersionCompareResponse(
        version_name=ver.name,
        differences=diffs
    )
