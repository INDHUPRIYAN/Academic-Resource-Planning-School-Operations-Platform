from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.auth import get_current_user
from app import models, schemas

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("")
def list_notifications(
    unread_only: bool = False,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=500),
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    query = db.query(models.Notification).filter(models.Notification.user_id == user.id)
    if unread_only:
        query = query.filter(models.Notification.is_read.is_(False))
    total = query.count()
    unread_count = db.query(models.Notification).filter(
        models.Notification.user_id == user.id, models.Notification.is_read.is_(False)
    ).count()
    items = query.order_by(models.Notification.created_at.desc()).offset((page - 1) * limit).limit(limit).all()
    return {
        "items": [schemas.NotificationOut.model_validate(i) for i in items],
        "total": total,
        "unread_count": unread_count,
        "page": page,
        "limit": limit,
    }


@router.patch("/{notif_id}/read", response_model=schemas.NotificationOut)
def mark_read(notif_id: int, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    row = db.query(models.Notification).filter(
        models.Notification.id == notif_id, models.Notification.user_id == user.id
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="Notification not found")
    row.is_read = True
    db.commit()
    db.refresh(row)
    return row


@router.patch("/read-all")
def mark_all_read(db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    db.query(models.Notification).filter(
        models.Notification.user_id == user.id, models.Notification.is_read.is_(False)
    ).update({"is_read": True})
    db.commit()
    return {"status": "ok"}
