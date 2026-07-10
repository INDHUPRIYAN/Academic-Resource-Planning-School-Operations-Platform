from app.crud_factory import make_crud_router
from app import models, schemas

router = make_crud_router(
    model=models.CalendarEvent,
    out_schema=schemas.CalendarEventOut,
    create_schema=schemas.CalendarEventCreate,
    update_schema=schemas.CalendarEventUpdate,
    prefix="/calendar",
    tag="calendar",
    search_fields=["title", "type"],
    scope_field="school_id",
)
