from fastapi import Depends, HTTPException
from fastapi.routing import APIRoute
from sqlalchemy.orm import Session
from app.database import get_db
from app import models, schemas
from app.auth import get_current_user, require_roles
from app.models import School, RoleEnum
from app.schemas import SchoolOut, SchoolCreate, SchoolUpdate
from app.crud_factory import make_crud_router, log_action
from app.services.validation_engine import invalidate_cache as _invalidate_validation_cache

router = make_crud_router(
    model=School,
    out_schema=SchoolOut,
    create_schema=SchoolCreate,
    update_schema=SchoolUpdate,
    prefix="/schools",
    tag="school",
    search_fields=["name"],
    scope_field="id",
    write_roles=(RoleEnum.super_admin,),
)

# Remove default PUT route
router.routes = [r for r in router.routes if not (isinstance(r, APIRoute) and r.path.endswith("/{item_id}") and "PUT" in r.methods)]

@router.put("/{item_id}", response_model=SchoolOut)
def update_school(
    item_id: int,
    payload: SchoolUpdate,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_roles(RoleEnum.super_admin, RoleEnum.school_admin)),
):
    if user.role != RoleEnum.super_admin and user.school_id != item_id:
        raise HTTPException(status_code=403, detail="Not authorized to update this school's settings")
    
    school = db.query(School).filter(School.id == item_id).first()
    if not school:
        raise HTTPException(status_code=404, detail="School not found")
        
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(school, k, v)
        
    db.commit()
    db.refresh(school)
    
    log_action(db, user.id, "update_school", f"id={school.id}")
    _invalidate_validation_cache(item_id)
    return school


import json
from datetime import datetime

DEFAULT_CONFIG = {
    "school_type": "Other",
    "academic_year": "2026-2027",
    "period_timings": [
        {"period": 1, "start": "08:30", "end": "09:15"},
        {"period": 2, "start": "09:15", "end": "10:00"},
        {"period": 3, "start": "10:00", "end": "10:45"},
        {"period": 4, "start": "11:00", "end": "11:45"},
        {"period": 5, "start": "11:45", "end": "12:30"},
        {"period": 6, "start": "13:30", "end": "14:15"},
        {"period": 7, "start": "14:15", "end": "15:00"},
        {"period": 8, "start": "15:00", "end": "15:45"}
    ],
    "enabled_modules": ["timetables", "leaves", "swaps", "exams", "reports"],
    "academic_structure": {
        "grades": []
    },
    "sections_per_grade": {},
    "mediums": {
        "enabled": False,
        "list": []
    },
    "teacher_assignment_method": "automatic",
    "teacher_eligibility": {
        "enabled": False,
        "groups": []
    },
    "subject_configuration": {
        "hours_defined_at": "per_class"
    },
    "activities": {
        "enabled": False,
        "list": []
    },
    "resources": {
        "enabled": True
    },
    "substitution_policy": "automatic",
    "scheduling_policies": {
        "max_consecutive_periods": 3,
        "max_daily_periods": 8,
        "double_periods_allowed": False,
        "science_practical_consecutive": False,
        "pet_last_periods": False
    }
}

@router.get("/{item_id}/config", response_model=schemas.SchoolConfigOut)
def get_school_config(
    item_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_roles(RoleEnum.super_admin, RoleEnum.school_admin, RoleEnum.teacher))
):
    if user.role != RoleEnum.super_admin and user.school_id != item_id:
        raise HTTPException(status_code=403, detail="Not authorized to access this school's configuration")
    
    cfg = db.query(models.SchoolConfig).filter(models.SchoolConfig.school_id == item_id).first()
    if not cfg:
        # Create default config on the fly for backward compatibility
        cfg = models.SchoolConfig(
            school_id=item_id,
            config=json.dumps(DEFAULT_CONFIG),
            updated_at=datetime.utcnow()
        )
        db.add(cfg)
        db.commit()
        db.refresh(cfg)
    return cfg

@router.put("/{item_id}/config", response_model=schemas.SchoolConfigOut)
def update_school_config(
    item_id: int,
    payload: schemas.SchoolConfigUpdate,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_roles(RoleEnum.super_admin, RoleEnum.school_admin))
):
    if user.role != RoleEnum.super_admin and user.school_id != item_id:
        raise HTTPException(status_code=403, detail="Not authorized to update this school's configuration")
    
    # Validate payload JSON format
    try:
        json_data = json.loads(payload.config)
        if not isinstance(json_data, dict):
            raise ValueError()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON format for config")

    cfg = db.query(models.SchoolConfig).filter(models.SchoolConfig.school_id == item_id).first()
    if not cfg:
        cfg = models.SchoolConfig(school_id=item_id, config=payload.config)
        db.add(cfg)
    else:
        cfg.config = payload.config
    
    db.commit()
    db.refresh(cfg)
    log_action(db, user.id, "update_school_config", f"id={item_id}")
    _invalidate_validation_cache(item_id)
    return cfg


TEMPLATES = {
    "Government": {
        "school_type": "Government School",
        "academic_year": "2026-2027",
        "period_timings": [
            {"period": 1, "start": "09:30", "end": "10:15"},
            {"period": 2, "start": "10:15", "end": "11:00"},
            {"period": 3, "start": "11:15", "end": "12:00"},
            {"period": 4, "start": "12:00", "end": "12:45"},
            {"period": 5, "start": "13:30", "end": "14:15"},
            {"period": 6, "start": "14:15", "end": "15:00"},
            {"period": 7, "start": "15:15", "end": "16:00"},
            {"period": 8, "start": "16:00", "end": "16:45"}
        ],
        "enabled_modules": ["timetables", "leaves", "swaps", "reports"],
        "academic_structure": {"grades": ["Grade 6", "Grade 7", "Grade 8", "Grade 9", "Grade 10"]},
        "sections_per_grade": {},
        "mediums": {"enabled": True, "list": ["English", "Tamil"]},
        "teacher_assignment_method": "manual",
        "teacher_eligibility": {"enabled": False, "groups": []},
        "subject_configuration": {"hours_defined_at": "per_class"},
        "activities": {"enabled": False, "list": []},
        "resources": {"enabled": False},
        "substitution_policy": "manual",
        "scheduling_policies": {
            "max_consecutive_periods": 4,
            "max_daily_periods": 8,
            "double_periods_allowed": False,
            "science_practical_consecutive": False,
            "pet_last_periods": True
        }
    },
    "Private": {
        "school_type": "Private School",
        "academic_year": "2026-2027",
        "period_timings": [
            {"period": 1, "start": "08:30", "end": "09:15"},
            {"period": 2, "start": "09:15", "end": "10:00"},
            {"period": 3, "start": "10:00", "end": "10:45"},
            {"period": 4, "start": "11:00", "end": "11:45"},
            {"period": 5, "start": "11:45", "end": "12:30"},
            {"period": 6, "start": "13:30", "end": "14:15"},
            {"period": 7, "start": "14:15", "end": "15:00"},
            {"period": 8, "start": "15:00", "end": "15:45"}
        ],
        "enabled_modules": ["timetables", "leaves", "swaps", "exams", "reports"],
        "academic_structure": {"grades": ["Grade 1", "Grade 2", "Grade 3", "Grade 4", "Grade 5", "Grade 6", "Grade 7", "Grade 8"]},
        "sections_per_grade": {},
        "mediums": {"enabled": False, "list": ["English"]},
        "teacher_assignment_method": "automatic",
        "teacher_eligibility": {"enabled": False, "groups": []},
        "subject_configuration": {"hours_defined_at": "per_class"},
        "activities": {"enabled": True, "list": ["PET", "Library", "Computer Lab"]},
        "resources": {"enabled": True},
        "substitution_policy": "automatic",
        "scheduling_policies": {
            "max_consecutive_periods": 3,
            "max_daily_periods": 8,
            "double_periods_allowed": True,
            "science_practical_consecutive": True,
            "pet_last_periods": False
        }
    },
    "CBSE": {
        "school_type": "CBSE School",
        "academic_year": "2026-2027",
        "period_timings": [
            {"period": 1, "start": "08:30", "end": "09:15"},
            {"period": 2, "start": "09:15", "end": "10:00"},
            {"period": 3, "start": "10:00", "end": "10:45"},
            {"period": 4, "start": "11:00", "end": "11:45"},
            {"period": 5, "start": "11:45", "end": "12:30"},
            {"period": 6, "start": "13:30", "end": "14:15"},
            {"period": 7, "start": "14:15", "end": "15:00"},
            {"period": 8, "start": "15:00", "end": "15:45"}
        ],
        "enabled_modules": ["timetables", "leaves", "swaps", "exams", "reports"],
        "academic_structure": {"grades": ["Grade 6", "Grade 7", "Grade 8", "Grade 9", "Grade 10"]},
        "sections_per_grade": {},
        "mediums": {"enabled": False, "list": ["English"]},
        "teacher_assignment_method": "hybrid",
        "teacher_eligibility": {"enabled": True, "groups": [
            {"name": "Secondary Wing", "allowed_grades": ["Grade 9", "Grade 10"]},
            {"name": "Middle Wing", "allowed_grades": ["Grade 6", "Grade 7", "Grade 8"]}
        ]},
        "subject_configuration": {"hours_defined_at": "per_class"},
        "activities": {"enabled": True, "list": ["PET", "Library", "Computer Lab"]},
        "resources": {"enabled": True},
        "substitution_policy": "automatic",
        "scheduling_policies": {
            "max_consecutive_periods": 3,
            "max_daily_periods": 8,
            "double_periods_allowed": True,
            "science_practical_consecutive": True,
            "pet_last_periods": False
        }
    },
    "ICSE": {
        "school_type": "ICSE School",
        "academic_year": "2026-2027",
        "period_timings": [
            {"period": 1, "start": "08:30", "end": "09:15"},
            {"period": 2, "start": "09:15", "end": "10:00"},
            {"period": 3, "start": "10:00", "end": "10:45"},
            {"period": 4, "start": "11:00", "end": "11:45"},
            {"period": 5, "start": "11:45", "end": "12:30"},
            {"period": 6, "start": "13:30", "end": "14:15"},
            {"period": 7, "start": "14:15", "end": "15:00"},
            {"period": 8, "start": "15:00", "end": "15:45"}
        ],
        "enabled_modules": ["timetables", "leaves", "swaps", "exams", "reports"],
        "academic_structure": {"grades": ["Grade 6", "Grade 7", "Grade 8", "Grade 9", "Grade 10"]},
        "sections_per_grade": {},
        "mediums": {"enabled": False, "list": ["English"]},
        "teacher_assignment_method": "automatic",
        "teacher_eligibility": {"enabled": False, "groups": []},
        "subject_configuration": {"hours_defined_at": "per_class"},
        "activities": {"enabled": True, "list": ["PET", "Library", "Music", "Computer Lab"]},
        "resources": {"enabled": True},
        "substitution_policy": "automatic",
        "scheduling_policies": {
            "max_consecutive_periods": 3,
            "max_daily_periods": 8,
            "double_periods_allowed": True,
            "science_practical_consecutive": True,
            "pet_last_periods": False
        }
    },
    "Matriculation": {
        "school_type": "Matriculation School",
        "academic_year": "2026-2027",
        "period_timings": [
            {"period": 1, "start": "08:30", "end": "09:15"},
            {"period": 2, "start": "09:15", "end": "10:00"},
            {"period": 3, "start": "10:00", "end": "10:45"},
            {"period": 4, "start": "11:00", "end": "11:45"},
            {"period": 5, "start": "11:45", "end": "12:30"},
            {"period": 6, "start": "13:30", "end": "14:15"},
            {"period": 7, "start": "14:15", "end": "15:00"},
            {"period": 8, "start": "15:00", "end": "15:45"}
        ],
        "enabled_modules": ["timetables", "leaves", "swaps", "exams", "reports"],
        "academic_structure": {"grades": ["Grade 6", "Grade 7", "Grade 8", "Grade 9", "Grade 10"]},
        "sections_per_grade": {},
        "mediums": {"enabled": True, "list": ["English", "Tamil"]},
        "teacher_assignment_method": "hybrid",
        "teacher_eligibility": {"enabled": False, "groups": []},
        "subject_configuration": {"hours_defined_at": "per_class"},
        "activities": {"enabled": True, "list": ["PET", "Library"]},
        "resources": {"enabled": True},
        "substitution_policy": "automatic",
        "scheduling_policies": {
            "max_consecutive_periods": 3,
            "max_daily_periods": 8,
            "double_periods_allowed": False,
            "science_practical_consecutive": False,
            "pet_last_periods": True
        }
    },
    "Higher Secondary": {
        "school_type": "Higher Secondary School",
        "academic_year": "2026-2027",
        "period_timings": [
            {"period": 1, "start": "08:30", "end": "09:15"},
            {"period": 2, "start": "09:15", "end": "10:00"},
            {"period": 3, "start": "10:00", "end": "10:45"},
            {"period": 4, "start": "11:00", "end": "11:45"},
            {"period": 5, "start": "11:45", "end": "12:30"},
            {"period": 6, "start": "13:30", "end": "14:15"},
            {"period": 7, "start": "14:15", "end": "15:00"},
            {"period": 8, "start": "15:00", "end": "15:45"}
        ],
        "enabled_modules": ["timetables", "leaves", "swaps", "exams", "reports"],
        "academic_structure": {"grades": ["Grade 11", "Grade 12"]},
        "sections_per_grade": {},
        "mediums": {"enabled": True, "list": ["English", "Tamil"]},
        "teacher_assignment_method": "manual",
        "teacher_eligibility": {"enabled": True, "groups": [
            {"name": "Higher Secondary Wing", "allowed_grades": ["Grade 11", "Grade 12"]}
        ]},
        "subject_configuration": {"hours_defined_at": "per_class"},
        "activities": {"enabled": False, "list": []},
        "resources": {"enabled": True},
        "substitution_policy": "manual",
        "scheduling_policies": {
            "max_consecutive_periods": 4,
            "max_daily_periods": 8,
            "double_periods_allowed": True,
            "science_practical_consecutive": True,
            "pet_last_periods": True
        }
    }
}


@router.post("/{item_id}/apply-template", response_model=schemas.SchoolConfigOut)
def apply_school_template(
    item_id: int,
    payload: dict,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_roles(RoleEnum.super_admin, RoleEnum.school_admin))
):
    if user.role != RoleEnum.super_admin and user.school_id != item_id:
        raise HTTPException(status_code=403, detail="Not authorized to update this school's configuration")
    
    template_name = payload.get("template_name")
    if template_name not in TEMPLATES:
        raise HTTPException(status_code=400, detail="Invalid template name")
        
    tpl_data = TEMPLATES[template_name]
    
    cfg = db.query(models.SchoolConfig).filter(models.SchoolConfig.school_id == item_id).first()
    if not cfg:
        cfg = models.SchoolConfig(
            school_id=item_id,
            config=json.dumps(tpl_data),
            updated_at=datetime.utcnow()
        )
        db.add(cfg)
    else:
        cfg.config = json.dumps(tpl_data)
        cfg.updated_at = datetime.utcnow()
        
    db.commit()
    db.refresh(cfg)
    log_action(db, user.id, "apply_school_template", f"id={item_id} template={template_name}")
    _invalidate_validation_cache(item_id)
    return cfg

