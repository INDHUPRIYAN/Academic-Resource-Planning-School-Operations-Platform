from app.models import Activity
from app.schemas import ActivityOut, ActivityCreate, ActivityUpdate
from app.crud_factory import make_crud_router

router = make_crud_router(
    model=Activity,
    out_schema=ActivityOut,
    create_schema=ActivityCreate,
    update_schema=ActivityUpdate,
    prefix="/activities",
    tag="activity",
    search_fields=["name"],
    scope_field="school_id",
)
