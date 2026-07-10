from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import or_

from app.database import get_db
from app.auth import get_current_user, require_roles, hash_password
from app.crud_factory import log_action
from app import models, schemas
from app.services.validation_engine import invalidate_cache as _invalidate_validation_cache

router = APIRouter(prefix="/teachers", tags=["teacher"])

ADMIN_ROLES = (models.RoleEnum.super_admin, models.RoleEnum.school_admin)


def _class_teacher_label(t: models.Teacher) -> str:
    """"8 B" for the section they own, comma-separated if several, "-" if none."""
    labels = [
        f"{s.class_.name} {s.name}".strip() if s.class_ else s.name
        for s in sorted(t.class_teacher_of, key=lambda s: (s.class_.name if s.class_ else "", s.name))
    ]
    return ", ".join(labels) if labels else "-"


def to_out(t: models.Teacher) -> schemas.TeacherOut:
    return schemas.TeacherOut(
        id=t.id,
        school_id=t.school_id,
        department=t.department,
        max_weekly_hours=t.max_weekly_hours,
        name=t.user.name,
        email=t.user.email,
        is_active=t.user.is_active,
        subject_ids=[s.id for s in t.subjects],
        class_teacher_of=_class_teacher_label(t),
    )


def scoped(query, user):
    if user.role != models.RoleEnum.super_admin:
        query = query.filter(models.Teacher.school_id == user.school_id)
    return query


def get_or_404(db: Session, teacher_id: int, user):
    t = scoped(db.query(models.Teacher).options(joinedload(models.Teacher.user), joinedload(models.Teacher.subjects)), user) \
        .filter(models.Teacher.id == teacher_id).first()
    if not t:
        raise HTTPException(status_code=404, detail="Teacher not found")
    return t


@router.get("")
def list_teachers(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    search: str | None = None,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    query = scoped(
        db.query(models.Teacher).join(models.User).options(
            joinedload(models.Teacher.user),
            joinedload(models.Teacher.subjects),
            joinedload(models.Teacher.class_teacher_of).joinedload(models.Section.class_),
        ),
        user,
    )
    if search:
        like = f"%{search}%"
        query = query.filter(or_(models.User.name.ilike(like), models.User.email.ilike(like)))
    total = query.count()
    items = query.offset((page - 1) * limit).limit(limit).all()
    return {"items": [to_out(t) for t in items], "total": total, "page": page, "limit": limit}


@router.get("/{teacher_id}", response_model=schemas.TeacherOut)
def get_teacher(teacher_id: int, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    return to_out(get_or_404(db, teacher_id, user))


@router.post("", response_model=schemas.TeacherOut, status_code=201)
def create_teacher(
    payload: schemas.TeacherCreate,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_roles(*ADMIN_ROLES)),
):
    if db.query(models.User).filter(models.User.email == payload.email).first():
        raise HTTPException(status_code=400, detail="Email already in use")

    school_id = user.school_id if user.role == models.RoleEnum.school_admin else payload.school_id
    if not school_id:
        raise HTTPException(status_code=400, detail="school_id is required")

    new_user = models.User(
        name=payload.name,
        email=payload.email,
        hashed_password=hash_password(payload.password),
        role=models.RoleEnum.teacher,
        school_id=school_id,
    )
    db.add(new_user)
    db.flush()

    teacher = models.Teacher(
        user_id=new_user.id,
        school_id=school_id,
        department=payload.department,
        # Blank form field -> null; fall back to the default rather than storing NULL.
        max_weekly_hours=payload.max_weekly_hours or 30,
    )
    if payload.subject_ids:
        teacher.subjects = db.query(models.Subject).filter(models.Subject.id.in_(payload.subject_ids)).all()
    db.add(teacher)
    db.commit()
    db.refresh(teacher)
    log_action(db, user.id, "create_teacher", f"id={teacher.id}")
    _invalidate_validation_cache(teacher.school_id)
    return to_out(teacher)


@router.put("/{teacher_id}", response_model=schemas.TeacherOut)
def update_teacher(
    teacher_id: int,
    payload: schemas.TeacherUpdate,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_roles(*ADMIN_ROLES)),
):
    teacher = get_or_404(db, teacher_id, user)
    data = payload.model_dump(exclude_unset=True)
    # A cleared form field arrives as null; treat that as "unchanged" so the column
    # never becomes NULL — the scheduler does arithmetic on it.
    if data.get("max_weekly_hours") is None:
        data.pop("max_weekly_hours", None)
    subject_ids = data.pop("subject_ids", None)
    if "is_active" in data:
        teacher.user.is_active = data.pop("is_active")
    for k, v in data.items():
        setattr(teacher, k, v)
    if subject_ids is not None:
        teacher.subjects = db.query(models.Subject).filter(models.Subject.id.in_(subject_ids)).all()
    db.commit()
    db.refresh(teacher)
    log_action(db, user.id, "update_teacher", f"id={teacher.id}")
    _invalidate_validation_cache(teacher.school_id)
    return to_out(teacher)


@router.delete("/{teacher_id}", status_code=204)
def delete_teacher(
    teacher_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_roles(*ADMIN_ROLES)),
):
    from sqlalchemy.exc import IntegrityError

    teacher = get_or_404(db, teacher_id, user)
    sid = teacher.school_id

    # Name the blocking sections rather than silently clearing their class teacher.
    owned = (
        db.query(models.Section, models.Class)
        .join(models.Class, models.Section.class_id == models.Class.id)
        .filter(models.Section.class_teacher_id == teacher_id)
        .all()
    )
    if owned:
        labels = ", ".join(f"{c.name} {s.name}" for s, c in owned)
        raise HTTPException(
            status_code=409,
            detail=f"This teacher is the class teacher of: {labels}. "
                   f"Reassign those sections before deleting.",
        )

    db.delete(teacher)
    db.delete(teacher.user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Cannot delete this teacher: timetable rows or subject assignments still "
                   "reference them. Remove those first.",
        )
    log_action(db, user.id, "delete_teacher", f"id={teacher_id}")
    if sid:
        _invalidate_validation_cache(sid)
