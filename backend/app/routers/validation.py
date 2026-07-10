from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app import models, schemas
from app.auth import require_roles
from app.services.validation_engine import validation_registry, invalidate_cache

router = APIRouter(prefix="/validation", tags=["validation"])
ADMIN_ROLES = (models.RoleEnum.super_admin, models.RoleEnum.school_admin)

@router.get("/school/{school_id}", response_model=schemas.SchoolValidationResponse)
def validate_school_config(
    school_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_roles(*ADMIN_ROLES)),
):
    if user.role != models.RoleEnum.super_admin and school_id != user.school_id:
        raise HTTPException(status_code=403, detail="Cannot access different school's validation report")

    # Run the dynamic validation engine
    report = validation_registry.validate(school_id, db)
    if "error" in report:
        raise HTTPException(status_code=404, detail=report["error"])
        
    return report

@router.post("/school/{school_id}/invalidate")
def invalidate_school_validation_cache(
    school_id: int,
    user: models.User = Depends(require_roles(*ADMIN_ROLES)),
):
    if user.role != models.RoleEnum.super_admin and school_id != user.school_id:
        raise HTTPException(status_code=403, detail="Cannot modify different school's validation context")

    invalidate_cache(school_id)
    return {"message": "Validation cache invalidated successfully."}
