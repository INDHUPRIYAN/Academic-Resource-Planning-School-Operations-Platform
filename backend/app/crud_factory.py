from typing import Type
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.auth import get_current_user, require_roles
from app import models
from app.services.validation_engine import invalidate_cache as _invalidate_validation_cache


def log_action(db: Session, user_id: int, action: str, details: str = ""):
    db.add(models.AuditLog(user_id=user_id, action=action, details=details))
    db.commit()


def make_crud_router(
    model: Type,
    out_schema,
    create_schema,
    update_schema,
    prefix: str,
    tag: str,
    search_fields: list[str] | None = None,
    scope_field: str | None = "school_id",
    write_roles=(models.RoleEnum.super_admin, models.RoleEnum.school_admin),
):
    """Builds CRUD endpoints for a model. scope_field names the column compared
    against the caller's school_id to restrict non-super-admins to their own
    school's data (pass None to skip scoping)."""
    router = APIRouter(prefix=prefix, tags=[tag])

    def scoped(query, user):
        if scope_field and user.role != models.RoleEnum.super_admin:
            query = query.filter(getattr(model, scope_field) == user.school_id)
        return query

    def get_or_404(db: Session, item_id: int, user):
        item = scoped(db.query(model), user).filter(model.id == item_id).first()
        if not item:
            raise HTTPException(status_code=404, detail=f"{tag} not found")
        return item

    @router.get("")
    def list_items(
        page: int = Query(1, ge=1),
        limit: int = Query(20, ge=1, le=500),
        search: str | None = None,
        db: Session = Depends(get_db),
        user: models.User = Depends(get_current_user),
    ):
        query = scoped(db.query(model), user)
        if search and search_fields:
            like = f"%{search}%"
            query = query.filter(or_(*[getattr(model, f).ilike(like) for f in search_fields]))
        total = query.count()
        items = query.offset((page - 1) * limit).limit(limit).all()
        return {
            "items": [out_schema.model_validate(i) for i in items],
            "total": total,
            "page": page,
            "limit": limit,
        }

    @router.get("/{item_id}", response_model=out_schema)
    def get_item(item_id: int, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
        return get_or_404(db, item_id, user)

    @router.post("", response_model=out_schema, status_code=201)
    def create_item(
        payload: create_schema,
        db: Session = Depends(get_db),
        user: models.User = Depends(require_roles(*write_roles)),
    ):
        data = payload.model_dump()
        if scope_field and scope_field in [c.name for c in model.__table__.columns] and user.role != models.RoleEnum.super_admin:
            data[scope_field] = user.school_id
        obj = model(**data)
        db.add(obj)
        db.commit()
        db.refresh(obj)
        log_action(db, user.id, f"create_{tag}", f"id={obj.id}")
        if scope_field == "school_id":
            _invalidate_validation_cache(getattr(obj, scope_field, None))
        return obj

    @router.put("/{item_id}", response_model=out_schema)
    def update_item(
        item_id: int,
        payload: update_schema,
        db: Session = Depends(get_db),
        user: models.User = Depends(require_roles(*write_roles)),
    ):
        obj = get_or_404(db, item_id, user)
        for k, v in payload.model_dump(exclude_unset=True).items():
            setattr(obj, k, v)
        db.commit()
        db.refresh(obj)
        log_action(db, user.id, f"update_{tag}", f"id={obj.id}")
        if scope_field == "school_id":
            _invalidate_validation_cache(getattr(obj, scope_field, None))
        return obj

    @router.delete("/{item_id}", status_code=204)
    def delete_item(
        item_id: int,
        db: Session = Depends(get_db),
        user: models.User = Depends(require_roles(*write_roles)),
    ):
        obj = get_or_404(db, item_id, user)
        sid = getattr(obj, scope_field, None) if scope_field == "school_id" else None
        db.delete(obj)
        try:
            db.commit()
        except IntegrityError:
            # Dependent records still reference this row; report a conflict rather than a 500.
            db.rollback()
            raise HTTPException(
                status_code=409,
                detail=f"Cannot delete this {tag}: other records still reference it. "
                       f"Remove or reassign them first.",
            )
        log_action(db, user.id, f"delete_{tag}", f"id={item_id}")
        if sid:
            _invalidate_validation_cache(sid)

    return router
