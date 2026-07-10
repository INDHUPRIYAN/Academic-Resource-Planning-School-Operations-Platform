from app.models import Class
from app.schemas import ClassOut, ClassCreate, ClassUpdate
from app.crud_factory import make_crud_router

router = make_crud_router(
    model=Class,
    out_schema=ClassOut,
    create_schema=ClassCreate,
    update_schema=ClassUpdate,
    prefix="/classes",
    tag="class",
    search_fields=["name"],
    scope_field="school_id",
)
