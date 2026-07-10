from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload
from app.database import get_db
from app.auth import get_current_user, require_roles
from app.crud_factory import log_action
from app import models, schemas
from app.services.validation_engine import invalidate_cache as _invalidate_validation_cache

router = APIRouter(prefix="/assignments", tags=["assignments"])
ADMIN_ROLES = (models.RoleEnum.super_admin, models.RoleEnum.school_admin)

def scoped(query, user):
    if user.role != models.RoleEnum.super_admin:
        query = query.filter(models.SubjectAssignment.school_id == user.school_id)
    return query

def to_out(row: models.SubjectAssignment) -> schemas.SubjectAssignmentOut:
    return schemas.SubjectAssignmentOut(
        id=row.id,
        school_id=row.school_id,
        section_id=row.section_id,
        subject_id=row.subject_id,
        teacher_id=row.teacher_id,
        section_name=f"{row.section.class_.name} {row.section.name}" if row.section and row.section.class_ else None,
        subject_name=row.subject.name if row.subject else None,
        teacher_name=row.teacher.user.name if row.teacher and row.teacher.user else None
    )

@router.get("")
def list_assignments(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=500),
    section_id: int | None = None,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user)
):
    query = scoped(db.query(models.SubjectAssignment), user)
    if section_id:
        query = query.filter(models.SubjectAssignment.section_id == section_id)
        
    query = query.options(
        joinedload(models.SubjectAssignment.section).joinedload(models.Section.class_),
        joinedload(models.SubjectAssignment.subject),
        joinedload(models.SubjectAssignment.teacher).joinedload(models.Teacher.user)
    )
    
    total = query.count()
    items = query.offset((page - 1) * limit).limit(limit).all()
    return {
        "items": [to_out(i) for i in items],
        "total": total,
        "page": page,
        "limit": limit
    }

@router.post("", response_model=schemas.SubjectAssignmentOut, status_code=201)
def create_assignment(
    payload: schemas.SubjectAssignmentCreate,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_roles(*ADMIN_ROLES))
):
    school_id = user.school_id if user.role == models.RoleEnum.school_admin else payload.school_id
    if not school_id:
        raise HTTPException(status_code=400, detail="school_id is required")

    # Validate section and subject exist and are in the same school
    sec = db.query(models.Section).join(models.Class).filter(
        models.Section.id == payload.section_id,
        models.Class.school_id == school_id
    ).first()
    if not sec:
        raise HTTPException(status_code=400, detail="Invalid section_id")

    subj = db.query(models.Subject).filter(
        models.Subject.id == payload.subject_id,
        models.Subject.school_id == school_id
    ).first()
    if not subj:
        raise HTTPException(status_code=400, detail="Invalid subject_id")

    if payload.teacher_id:
        teacher = db.query(models.Teacher).filter(
            models.Teacher.id == payload.teacher_id,
            models.Teacher.school_id == school_id
        ).first()
        if not teacher:
            raise HTTPException(status_code=400, detail="Invalid teacher_id")

    # Check duplicate
    existing = db.query(models.SubjectAssignment).filter(
        models.SubjectAssignment.section_id == payload.section_id,
        models.SubjectAssignment.subject_id == payload.subject_id
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail="Assignment already exists for this class-subject combo")

    row = models.SubjectAssignment(
        school_id=school_id,
        section_id=payload.section_id,
        subject_id=payload.subject_id,
        teacher_id=payload.teacher_id
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    
    # Reload with joins for to_out mapping
    row = db.query(models.SubjectAssignment).options(
        joinedload(models.SubjectAssignment.section).joinedload(models.Section.class_),
        joinedload(models.SubjectAssignment.subject),
        joinedload(models.SubjectAssignment.teacher).joinedload(models.Teacher.user)
    ).filter(models.SubjectAssignment.id == row.id).first()
    
    log_action(db, user.id, "create_assignment", f"id={row.id}")
    _invalidate_validation_cache(school_id)
    return to_out(row)

@router.put("/{id}", response_model=schemas.SubjectAssignmentOut)
def update_assignment(
    id: int,
    payload: schemas.SubjectAssignmentUpdate,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_roles(*ADMIN_ROLES))
):
    row = db.query(models.SubjectAssignment).filter(models.SubjectAssignment.id == id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Assignment not found")
        
    if user.role != models.RoleEnum.super_admin and row.school_id != user.school_id:
        raise HTTPException(status_code=403, detail="Not authorized to edit this assignment")

    if payload.teacher_id:
        teacher = db.query(models.Teacher).filter(
            models.Teacher.id == payload.teacher_id,
            models.Teacher.school_id == row.school_id
        ).first()
        if not teacher:
            raise HTTPException(status_code=400, detail="Invalid teacher_id")
        row.teacher_id = payload.teacher_id
    else:
        row.teacher_id = None
        
    db.commit()
    db.refresh(row)
    
    # Reload with joins
    row = db.query(models.SubjectAssignment).options(
        joinedload(models.SubjectAssignment.section).joinedload(models.Section.class_),
        joinedload(models.SubjectAssignment.subject),
        joinedload(models.SubjectAssignment.teacher).joinedload(models.Teacher.user)
    ).filter(models.SubjectAssignment.id == row.id).first()
    
    log_action(db, user.id, "update_assignment", f"id={row.id}")
    _invalidate_validation_cache(row.school_id)
    return to_out(row)

@router.delete("/{id}", status_code=204)
def delete_assignment(
    id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_roles(*ADMIN_ROLES))
):
    row = db.query(models.SubjectAssignment).filter(models.SubjectAssignment.id == id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Assignment not found")
        
    if user.role != models.RoleEnum.super_admin and row.school_id != user.school_id:
        raise HTTPException(status_code=403, detail="Not authorized to delete this assignment")
        
    sid = row.school_id
    db.delete(row)
    db.commit()
    log_action(db, user.id, "delete_assignment", f"id={id}")
    _invalidate_validation_cache(sid)
