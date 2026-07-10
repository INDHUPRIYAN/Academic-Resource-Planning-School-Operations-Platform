from app.models import Resource
from app.schemas import ResourceOut, ResourceCreate, ResourceUpdate
from app.crud_factory import make_crud_router

router = make_crud_router(
    model=Resource,
    out_schema=ResourceOut,
    create_schema=ResourceCreate,
    update_schema=ResourceUpdate,
    prefix="/resources",
    tag="resource",
    search_fields=["name", "type"],
    scope_field="school_id",
)
