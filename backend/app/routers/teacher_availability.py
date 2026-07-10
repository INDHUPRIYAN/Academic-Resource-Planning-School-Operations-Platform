from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.database import get_db
from app.auth import get_current_user, require_roles
from app import models, schemas
from app.crud_factory import log_action
from app.services.validation_engine import invalidate_cache as _invalidate_validation_cache

router = APIRouter(prefix="/teachers", tags=["teacher_availability"])

def assert_teacher_access(db: Session, teacher_id: int, user: models.User):
    teacher = db.query(models.Teacher).filter(models.Teacher.id == teacher_id).first()
    if not teacher:
        raise HTTPException(status_code=404, detail="Teacher not found")
    if user.role == models.RoleEnum.teacher:
        if teacher.user_id != user.id:
            raise HTTPException(status_code=403, detail="Not authorized to access another teacher's data")
    elif user.role != models.RoleEnum.super_admin:
        if teacher.school_id != user.school_id:
            raise HTTPException(status_code=403, detail="Teacher belongs to a different school")
    return teacher

@router.get("/{id}/availability", response_model=list[schemas.TeacherAvailabilityOut])
def get_teacher_availability(
    id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user)
):
    assert_teacher_access(db, id, user)
    return db.query(models.TeacherAvailability).filter(models.TeacherAvailability.teacher_id == id).all()

@router.put("/{id}/availability", response_model=list[schemas.TeacherAvailabilityOut])
def update_teacher_availability(
    id: int,
    payload: list[schemas.TeacherAvailabilityCreate],
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user)
):
    teacher = assert_teacher_access(db, id, user)
    
    # Remove existing availability grid
    db.query(models.TeacherAvailability).filter(models.TeacherAvailability.teacher_id == id).delete()
    
    # Bulk insert new grid
    new_records = []
    for item in payload:
        rec = models.TeacherAvailability(
            teacher_id=id,
            day_of_week=item.day_of_week,
            period=item.period,
            is_available=item.is_available
        )
        db.add(rec)
        new_records.append(rec)
        
    db.commit()
    for rec in new_records:
        db.refresh(rec)
        
    log_action(db, user.id, "update_teacher_availability", f"teacher_id={id} count={len(new_records)}")
    _invalidate_validation_cache(teacher.school_id)
    return new_records

@router.get("/{id}/preferences", response_model=list[schemas.TeacherPreferenceOut])
def get_teacher_preferences(
    id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user)
):
    assert_teacher_access(db, id, user)
    return db.query(models.TeacherPreference).filter(models.TeacherPreference.teacher_id == id).all()

@router.post("/{id}/preferences", response_model=schemas.TeacherPreferenceOut, status_code=status.HTTP_201_CREATED)
def add_teacher_preference(
    id: int,
    payload: schemas.TeacherPreferenceCreate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user)
):
    teacher = assert_teacher_access(db, id, user)
    
    pref = models.TeacherPreference(
        teacher_id=id,
        preference_type=payload.preference_type,
        day_of_week=payload.day_of_week,
        period=payload.period,
        value=payload.value,
        weight=payload.weight
    )
    db.add(pref)
    db.commit()
    db.refresh(pref)
    
    log_action(db, user.id, "add_teacher_preference", f"teacher_id={id} pref_id={pref.id} type={payload.preference_type}")
    _invalidate_validation_cache(teacher.school_id)
    return pref

@router.delete("/{id}/preferences/{pref_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_teacher_preference(
    id: int,
    pref_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user)
):
    teacher = assert_teacher_access(db, id, user)
    
    pref = db.query(models.TeacherPreference).filter(
        models.TeacherPreference.id == pref_id,
        models.TeacherPreference.teacher_id == id
    ).first()
    
    if not pref:
        raise HTTPException(status_code=404, detail="Preference not found")
        
    db.delete(pref)
    db.commit()
    
    log_action(db, user.id, "delete_teacher_preference", f"teacher_id={id} pref_id={pref_id}")
    _invalidate_validation_cache(teacher.school_id)
