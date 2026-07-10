from app.models import Subject
from app.schemas import SubjectOut, SubjectCreate, SubjectUpdate
from app.crud_factory import make_crud_router

router = make_crud_router(
    model=Subject,
    out_schema=SubjectOut,
    create_schema=SubjectCreate,
    update_schema=SubjectUpdate,
    prefix="/subjects",
    tag="subject",
    search_fields=["name"],
    scope_field="school_id",
)
