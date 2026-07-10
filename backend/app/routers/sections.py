import json

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.auth import get_current_user, require_roles
from app.crud_factory import log_action
from app import models, schemas
from app.services.validation_engine import invalidate_cache as _invalidate_validation_cache

router = APIRouter(prefix="/sections", tags=["section"])
ADMIN_ROLES = (models.RoleEnum.super_admin, models.RoleEnum.school_admin)


def scoped(query, user):
    query = query.join(models.Class, models.Section.class_id == models.Class.id)
    if user.role != models.RoleEnum.super_admin:
        query = query.filter(models.Class.school_id == user.school_id)
    return query


def get_or_404(db: Session, section_id: int, user):
    section = scoped(db.query(models.Section), user).filter(models.Section.id == section_id).first()
    if not section:
        raise HTTPException(status_code=404, detail="Section not found")
    return section


def assert_class_in_scope(db: Session, class_id: int, user) -> models.Class:
    cls = db.query(models.Class).filter(models.Class.id == class_id).first()
    if not cls:
        raise HTTPException(status_code=400, detail="Invalid class_id")
    if user.role != models.RoleEnum.super_admin and cls.school_id != user.school_id:
        raise HTTPException(status_code=403, detail="Class belongs to a different school")
    return cls


def assert_teacher_in_school(db: Session, teacher_id: int | None, school_id: int):
    if teacher_id is None:
        return
    teacher = db.query(models.Teacher).filter(models.Teacher.id == teacher_id).first()
    if not teacher:
        raise HTTPException(status_code=400, detail="Invalid class_teacher_id")
    if teacher.school_id != school_id:
        raise HTTPException(status_code=400, detail="Class teacher belongs to a different school")


def assert_medium_allowed(db: Session, medium: str | None, school_id: int):
    """Constrain the medium only when the school has configured a list. The naming
    convention that maps a section to a medium is a per-school policy and lives in
    the UI, never here."""
    if not medium:
        return
    row = db.query(models.SchoolConfig).filter(models.SchoolConfig.school_id == school_id).first()
    if not row:
        return
    try:
        cfg = json.loads(row.config)
    except (ValueError, TypeError):
        return
    mediums = cfg.get("mediums") or {}
    if not isinstance(mediums, dict) or not mediums.get("enabled"):
        return
    allowed = mediums.get("list") or []
    if allowed and medium not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"Medium '{medium}' is not configured for this school. Allowed: {', '.join(allowed)}",
        )


def to_out(section: models.Section) -> schemas.SectionOut:
    cls = section.class_
    teacher = section.class_teacher
    class_name = cls.name if cls else None
    return schemas.SectionOut(
        id=section.id,
        name=section.name,
        class_id=section.class_id,
        medium=section.medium,
        class_teacher_id=section.class_teacher_id,
        class_name=class_name,
        school_id=cls.school_id if cls else None,
        class_teacher_name=teacher.user.name if teacher and teacher.user else None,
        display_name=f"{class_name} {section.name}".strip() if class_name else section.name,
    )


def _with_joins(query):
    return query.options(
        joinedload(models.Section.class_),
        joinedload(models.Section.class_teacher).joinedload(models.Teacher.user),
    )


@router.get("")
def list_sections(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=500),
    search: str | None = None,
    class_id: int | None = None,
    school_id: int | None = None,
    medium: str | None = None,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    query = _with_joins(scoped(db.query(models.Section), user))
    if search:
        query = query.filter(models.Section.name.ilike(f"%{search}%"))
    if class_id:
        query = query.filter(models.Section.class_id == class_id)
    if school_id:
        query = query.filter(models.Class.school_id == school_id)
    if medium:
        query = query.filter(models.Section.medium == medium)
    total = query.count()
    items = (
        query.order_by(models.Class.name, models.Section.name)
        .offset((page - 1) * limit)
        .limit(limit)
        .all()
    )
    return {
        "items": [to_out(i) for i in items],
        "total": total,
        "page": page,
        "limit": limit,
    }


@router.get("/{section_id}", response_model=schemas.SectionOut)
def get_section(section_id: int, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    return to_out(get_or_404(db, section_id, user))


@router.post("", response_model=schemas.SectionOut, status_code=201)
def create_section(
    payload: schemas.SectionCreate,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_roles(*ADMIN_ROLES)),
):
    cls = assert_class_in_scope(db, payload.class_id, user)
    assert_teacher_in_school(db, payload.class_teacher_id, cls.school_id)
    assert_medium_allowed(db, payload.medium, cls.school_id)

    section = models.Section(**payload.model_dump())
    db.add(section)
    db.commit()
    db.refresh(section)
    log_action(db, user.id, "create_section", f"id={section.id}")
    _invalidate_validation_cache(cls.school_id)
    return to_out(section)


@router.post("/bulk", response_model=list[schemas.SectionOut], status_code=201)
def create_sections_bulk(
    payload: schemas.SectionBulkCreate,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_roles(*ADMIN_ROLES)),
):
    """Create every section of a class atomically — the 'Class 6 -> which sections?'
    onboarding step. All succeed or none do."""
    cls = assert_class_in_scope(db, payload.class_id, user)
    if not payload.sections:
        raise HTTPException(status_code=400, detail="Provide at least one section")

    names = [s.name.strip() for s in payload.sections]
    if any(not n for n in names):
        raise HTTPException(status_code=400, detail="Section names cannot be blank")
    if len(set(names)) != len(names):
        raise HTTPException(status_code=400, detail="Duplicate section names in request")

    existing = {
        s.name for s in db.query(models.Section).filter(models.Section.class_id == payload.class_id).all()
    }
    clash = sorted(existing.intersection(names))
    if clash:
        raise HTTPException(
            status_code=409,
            detail=f"Section(s) already exist in {cls.name}: {', '.join(clash)}",
        )

    created = []
    for item in payload.sections:
        assert_teacher_in_school(db, item.class_teacher_id, cls.school_id)
        assert_medium_allowed(db, item.medium, cls.school_id)
        created.append(models.Section(
            class_id=payload.class_id,
            name=item.name.strip(),
            medium=item.medium,
            class_teacher_id=item.class_teacher_id,
        ))

    db.add_all(created)
    db.commit()
    for s in created:
        db.refresh(s)
    log_action(db, user.id, "create_sections_bulk", f"class_id={payload.class_id} count={len(created)}")
    _invalidate_validation_cache(cls.school_id)
    return [to_out(s) for s in created]


@router.put("/{section_id}", response_model=schemas.SectionOut)
def update_section(
    section_id: int,
    payload: schemas.SectionUpdate,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_roles(*ADMIN_ROLES)),
):
    section = get_or_404(db, section_id, user)
    data = payload.model_dump(exclude_unset=True)

    cls = assert_class_in_scope(db, data["class_id"], user) if "class_id" in data else section.class_
    if "class_teacher_id" in data:
        assert_teacher_in_school(db, data["class_teacher_id"], cls.school_id)
    if "medium" in data:
        assert_medium_allowed(db, data["medium"], cls.school_id)

    for k, v in data.items():
        setattr(section, k, v)
    db.commit()
    db.refresh(section)
    log_action(db, user.id, "update_section", f"id={section.id}")
    _invalidate_validation_cache(cls.school_id)
    return to_out(section)


@router.delete("/{section_id}", status_code=204)
def delete_section(
    section_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_roles(*ADMIN_ROLES)),
):
    from sqlalchemy.exc import IntegrityError

    section = get_or_404(db, section_id, user)
    cls = section.class_
    school_id = cls.school_id if cls else None
    db.delete(section)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Cannot delete this section: timetable rows or assignments still reference it.",
        )
    log_action(db, user.id, "delete_section", f"id={section_id}")
    if school_id:
        _invalidate_validation_cache(school_id)
