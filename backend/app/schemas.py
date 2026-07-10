from datetime import date, datetime, time
from datetime import date as _date  # alias needed for ExamUpdate.date: see comment there
from pydantic import BaseModel, EmailStr, Field
from app.models import RoleEnum, LeaveStatus, SwapStatus


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: RoleEnum
    name: str


class UserOut(BaseModel):
    id: int
    name: str
    email: EmailStr
    role: RoleEnum
    school_id: int | None = None
    is_active: bool

    class Config:
        from_attributes = True


class UserCreate(BaseModel):
    name: str
    email: EmailStr
    password: str
    role: RoleEnum
    school_id: int | None = None


# ---- Schools ----
class SchoolBase(BaseModel):
    name: str
    address: str | None = None
    phone: str | None = None
    periods_per_day: int = 8
    working_days: int = 5


class SchoolCreate(SchoolBase):
    pass


class SchoolUpdate(BaseModel):
    name: str | None = None
    address: str | None = None
    phone: str | None = None
    periods_per_day: int | None = None
    working_days: int | None = None


class SchoolOut(SchoolBase):
    id: int

    class Config:
        from_attributes = True


# ---- Classes ----
class ClassBase(BaseModel):
    name: str


class ClassCreate(ClassBase):
    school_id: int | None = None


class ClassUpdate(BaseModel):
    name: str | None = None


class ClassOut(ClassBase):
    id: int
    school_id: int

    class Config:
        from_attributes = True


# ---- Sections ----
class SectionBase(BaseModel):
    name: str
    class_id: int
    medium: str | None = None
    class_teacher_id: int | None = None


class SectionCreate(SectionBase):
    pass


class SectionUpdate(BaseModel):
    name: str | None = None
    class_id: int | None = None
    medium: str | None = None
    class_teacher_id: int | None = None


class SectionOut(SectionBase):
    id: int
    # Denormalised for display: without class_name a UI cannot tell "6 A" from "7 A".
    class_name: str | None = None
    school_id: int | None = None
    class_teacher_name: str | None = None
    display_name: str | None = None

    class Config:
        from_attributes = True


class SectionBulkItem(BaseModel):
    name: str
    medium: str | None = None
    class_teacher_id: int | None = None


class SectionBulkCreate(BaseModel):
    """Create all sections of a class in one transaction so a partial failure never
    leaves a class with half its sections."""
    class_id: int
    sections: list[SectionBulkItem]


# ---- Subjects ----
class SubjectBase(BaseModel):
    name: str
    weekly_hours: int = 1
    resource_id: int | None = None


class SubjectCreate(SubjectBase):
    school_id: int | None = None


class SubjectUpdate(BaseModel):
    name: str | None = None
    weekly_hours: int | None = None
    resource_id: int | None = None


class SubjectOut(SubjectBase):
    id: int
    school_id: int

    class Config:
        from_attributes = True


# ---- Activities ----
class ActivityBase(BaseModel):
    name: str
    weekly_hours: int = 1
    resource_id: int | None = None


class ActivityCreate(ActivityBase):
    school_id: int | None = None


class ActivityUpdate(BaseModel):
    name: str | None = None
    weekly_hours: int | None = None
    resource_id: int | None = None


class ActivityOut(ActivityBase):
    id: int
    school_id: int

    class Config:
        from_attributes = True


# ---- Resources ----
class ResourceBase(BaseModel):
    name: str
    type: str | None = None
    capacity: int | None = None


class ResourceCreate(ResourceBase):
    school_id: int | None = None


class ResourceUpdate(BaseModel):
    name: str | None = None
    type: str | None = None
    capacity: int | None = None


class ResourceOut(ResourceBase):
    id: int
    school_id: int

    class Config:
        from_attributes = True


# ---- Teachers ----
class TeacherCreate(BaseModel):
    name: str
    email: EmailStr
    password: str
    department: str | None = None
    # Nullable so a blank form field means "use the default" rather than 422.
    # The scheduler subtracts from this value, so it must never reach the DB as NULL.
    max_weekly_hours: int | None = Field(default=30, ge=1, le=80)
    school_id: int | None = None
    subject_ids: list[int] = []


class TeacherUpdate(BaseModel):
    department: str | None = None
    # A null here means "leave unchanged" — the router drops it. See create note.
    max_weekly_hours: int | None = Field(default=None, ge=1, le=80)
    is_active: bool | None = None
    subject_ids: list[int] | None = None


class TeacherOut(BaseModel):
    id: int
    school_id: int
    department: str | None
    max_weekly_hours: int
    name: str
    email: EmailStr
    is_active: bool
    subject_ids: list[int] = []
    # Section(s) this teacher is class teacher of, e.g. "8 B". "-" when none.
    class_teacher_of: str = "-"

    class Config:
        from_attributes = True


# ---- Timetables ----
class TimetableGenerateRequest(BaseModel):
    school_id: int | None = None  # required for super_admin, ignored (forced) for school_admin
    time_limit_seconds: int = 30


class TimetableGenerateResponse(BaseModel):
    school_id: int
    slots_created: int
    sections_scheduled: int
    optimal: bool
    message: str
    # Rule 21: which hard constraints were independently re-verified after solving.
    verification: dict | None = None


class TimetableSlotUpdate(BaseModel):
    """Manual admin override of a single slot."""
    subject_id: int | None = None
    teacher_id: int | None = None
    activity_id: int | None = None
    resource_id: int | None = None
    day_of_week: int | None = None
    period: int | None = None


class TimetableOut(BaseModel):
    id: int
    school_id: int
    section_id: int
    subject_id: int | None
    teacher_id: int | None
    activity_id: int | None
    resource_id: int | None
    day_of_week: int
    period: int
    is_locked: bool

    class Config:
        from_attributes = True


class TimetableSlotOut(BaseModel):
    """Denormalized slot for grid display (avoids N+1 lookups on the frontend)."""
    id: int
    section_id: int
    section_name: str
    day_of_week: int
    period: int
    is_locked: bool
    kind: str  # "subject" | "activity" | "free"
    subject_id: int | None = None
    subject_name: str | None = None
    teacher_id: int | None = None
    teacher_name: str | None = None
    activity_id: int | None = None
    activity_name: str | None = None
    resource_id: int | None = None
    resource_name: str | None = None


# ---- Leaves (Phase 4) ----
class LeaveCreate(BaseModel):
    teacher_id: int | None = None  # admin only; teachers always apply for themselves
    date: date
    end_date: date | None = None  # omit for a single-day leave
    reason: str | None = None


class LeaveDecision(BaseModel):
    note: str | None = None


class LeaveOut(BaseModel):
    id: int
    teacher_id: int
    teacher_name: str
    school_id: int
    date: date
    end_date: date | None
    reason: str | None
    status: LeaveStatus
    decision_note: str | None
    reviewed_by: int | None
    reviewed_at: datetime | None
    created_at: datetime

    class Config:
        from_attributes = True


class UncoveredSlotOut(BaseModel):
    """A master-timetable slot on an approved-leave date that the auto
    engine could not staff at all (no other teacher exists at the school)."""
    timetable_id: int
    date: date
    day_of_week: int
    period: int
    section_name: str
    subject_name: str | None = None
    activity_name: str | None = None
    reason: str


class LeaveApprovalResult(BaseModel):
    leave: LeaveOut
    substitutions_created: int
    uncovered_slots: list[UncoveredSlotOut]
    message: str


# ---- Substitutions (Phase 4) ----
class SubstitutionCreate(BaseModel):
    """Manual assignment for a slot the auto engine left uncovered (or to
    override an existing assignment by deleting it first)."""
    leave_id: int
    timetable_id: int
    substitute_teacher_id: int
    date: date


class SubstitutionUpdate(BaseModel):
    substitute_teacher_id: int


class SubstitutionOut(BaseModel):
    id: int
    leave_id: int
    timetable_id: int
    substitute_teacher_id: int
    substitute_teacher_name: str
    original_teacher_name: str
    date: date
    method: str | None
    reason: str | None
    assigned_by: int | None
    day_of_week: int
    period: int
    section_name: str
    subject_name: str | None = None
    activity_name: str | None = None

    class Config:
        from_attributes = True


class EffectiveSlotOut(BaseModel):
    """One slot in the Layer-2 effective (overlaid) schedule for a specific date."""
    timetable_id: int
    day_of_week: int
    period: int
    section_id: int
    section_name: str
    kind: str
    subject_name: str | None = None
    activity_name: str | None = None
    resource_name: str | None = None
    teacher_id: int | None = None
    teacher_name: str | None = None
    is_substituted: bool = False
    original_teacher_name: str | None = None
    # Additive (Phase 5): set when an approved Swap (not a Substitution)
    # supplies this slot's effective content for this date.
    is_swapped: bool = False
    swap_partner_label: str | None = None


# ---- Notifications (Phase 4) ----
class NotificationOut(BaseModel):
    id: int
    message: str
    is_read: bool
    created_at: datetime

    class Config:
        from_attributes = True

# ---- Swaps (Phase 5) ----
class SwapCreate(BaseModel):
    """Request to swap two master-timetable slots' effective content for a
    single date. Both slots must share the same day_of_week, and that
    day_of_week must match `date`'s weekday (a swap is a same-day exchange
    of periods/classes, not a move to a different day)."""
    timetable_id_a: int
    timetable_id_b: int
    date: date
    reason: str | None = None


class SwapDecision(BaseModel):
    note: str | None = None


class SwapOut(BaseModel):
    id: int
    timetable_id_a: int
    timetable_id_b: int
    slot_a_label: str
    slot_b_label: str
    date: date
    status: SwapStatus
    requested_by: int | None
    requested_by_name: str | None = None
    reason: str | None
    decision_note: str | None
    approved_by: int | None
    reviewed_by: int | None
    reviewed_at: datetime | None
    created_at: datetime

    class Config:
        from_attributes = True


# ---- Exams (Phase 6) ----
class ExamCreate(BaseModel):
    subject_id: int
    section_id: int
    resource_id: int | None = None
    invigilator_id: int | None = None
    date: date
    start_time: time
    end_time: time


class ExamUpdate(BaseModel):
    subject_id: int | None = None
    section_id: int | None = None
    resource_id: int | None = None
    invigilator_id: int | None = None
    date: _date | None = None
    start_time: time | None = None
    end_time: time | None = None


class ExamOut(BaseModel):
    id: int
    school_id: int
    subject_id: int
    subject_name: str
    section_id: int
    section_name: str
    resource_id: int | None
    resource_name: str | None = None
    invigilator_id: int | None
    invigilator_name: str | None = None
    date: date
    start_time: time
    end_time: time

    class Config:
        from_attributes = True


class ExamGenerateRequest(BaseModel):
    """Greedy exam-timetable generator. Not CP-SAT (see README rationale):
    exam scheduling here just needs "no double-booking", which a simple
    earliest-available-slot placement satisfies without needing a solver."""
    school_id: int | None = None  # required for super_admin, forced for school_admin
    section_ids: list[int] | None = None  # default: every section in the school
    start_date: date
    end_date: date
    exams_per_day: int = 2
    daily_start_time: time = time(9, 0)
    duration_minutes: int = 90
    gap_minutes: int = 30
    # Optional: restrict rooms used for exams that don't have a fixed
    # subject.resource_id (e.g. a lab). If omitted, any Resource in the
    # school may be used; if the school has no resources, exams are still
    # scheduled with resource_id left null (room assignment becomes a
    # manual admin task).
    resource_ids: list[int] | None = None


class ExamGenerateUnscheduled(BaseModel):
    section_id: int
    section_name: str
    subject_id: int
    subject_name: str
    reason: str


class ExamGenerateResponse(BaseModel):
    school_id: int
    exams_created: int
    unscheduled: list[ExamGenerateUnscheduled]
    message: str


# ---- Versioning (Phase 10) ----
from datetime import datetime as datetime_cls

class TimetableVersionOut(BaseModel):
    id: int
    school_id: int
    name: str
    status: str
    created_at: datetime_cls
    created_by_id: int | None = None
    created_by_name: str | None = None
    published_by_id: int | None = None
    published_by_name: str | None = None
    published_time: datetime_cls | None = None
    reason: str | None = None
    generation_policy: str | None = None
    academic_year: str | None = None
    term: str | None = None
    semester: str | None = None

    class Config:
        from_attributes = True


class TimetableVersionCreate(BaseModel):
    school_id: int | None = None
    name: str
    reason: str | None = None
    generation_policy: str | None = None
    academic_year: str | None = None
    term: str | None = None
    semester: str | None = None


class TimetableVersionCompareSlot(BaseModel):
    day_of_week: int
    period: int
    section_name: str
    active_details: str | None = None
    version_details: str | None = None


class TimetableVersionCompareResponse(BaseModel):
    version_name: str
    differences: list[TimetableVersionCompareSlot]


# ---- Validation (Phase 5) ----
class ValidationItem(BaseModel):
    type: str
    message: str
    details: str | None = None


class SchoolValidationResponse(BaseModel):
    school_id: int
    readiness_score: int
    category_scores: dict[str, int]
    categories: dict
    quality_score: dict
    ready_to_generate: bool
    ready_to_publish: bool
    timestamp: float


# ---- Assistant (Phase 8) ----
class ExplainConflictRequest(BaseModel):
    detail: str
    context: dict | None = None


class ExplainConflictResponse(BaseModel):
    explanation: str


class ExplainInfeasibilityRequest(BaseModel):
    errors: list[str]
    warnings: list[str] = []


class ExplainInfeasibilityResponse(BaseModel):
    explanation: str


class ConflictDetail(BaseModel):
    problem: str
    reason: str
    suggested_fix: str
    auto_fix_available: bool
    estimated_impact: str


class AssistantSuggestionsRequest(BaseModel):
    conflicts: list[ConflictDetail]


class AssistantSuggestionsResponse(BaseModel):
    narrative: str
    suggestions: list[dict]


class WorkloadSuggestionsResponse(BaseModel):
    based_on: dict
    suggestions: str


class NarrateReportRequest(BaseModel):
    report_type: str
    school_id: int | None = None
    start_date: _date | None = None
    end_date: _date | None = None


class NarrateReportResponse(BaseModel):
    narrative: str


class ChatRequest(BaseModel):
    message: str
    school_id: int | None = None


class ChatResponse(BaseModel):
    reply: str


# ---- Universal Timetable Configuration & Assignments ----
class SchoolConfigOut(BaseModel):
    school_id: int
    config: str
    updated_at: datetime

    class Config:
        from_attributes = True


class SchoolConfigUpdate(BaseModel):
    config: str


class SubjectAssignmentBase(BaseModel):
    section_id: int
    subject_id: int
    teacher_id: int | None = None
    weekly_hours_override: int | None = None


class SubjectAssignmentCreate(SubjectAssignmentBase):
    school_id: int | None = None


class SubjectAssignmentUpdate(BaseModel):
    teacher_id: int | None = None
    weekly_hours_override: int | None = None


class SubjectAssignmentOut(SubjectAssignmentBase):
    id: int
    school_id: int
    section_name: str | None = None
    subject_name: str | None = None
    teacher_name: str | None = None

    class Config:
        from_attributes = True


class TeachingGroupBase(BaseModel):
    name: str
    allowed_grades: str


class TeachingGroupCreate(TeachingGroupBase):
    school_id: int | None = None


class TeachingGroupOut(TeachingGroupBase):
    id: int
    school_id: int

    class Config:
        from_attributes = True


class CalendarEventBase(BaseModel):
    title: str
    date: _date
    end_date: _date | None = None
    type: str  # holiday, exam_week, special_event
    is_holiday: bool = True


class CalendarEventCreate(CalendarEventBase):
    school_id: int | None = None


class CalendarEventUpdate(BaseModel):
    title: str | None = None
    date: _date | None = None
    end_date: _date | None = None
    type: str | None = None
    is_holiday: bool | None = None


class CalendarEventOut(CalendarEventBase):
    id: int
    school_id: int

    class Config:
        from_attributes = True


# ---- Teacher Availability & Preferences (Universal Timetable Engine) ----
class TeacherAvailabilityBase(BaseModel):
    day_of_week: int
    period: int
    is_available: bool = True

class TeacherAvailabilityCreate(TeacherAvailabilityBase):
    pass

class TeacherAvailabilityOut(TeacherAvailabilityBase):
    id: int
    teacher_id: int

    class Config:
        from_attributes = True

class TeacherAvailabilityBulkUpdate(BaseModel):
    availabilities: list[TeacherAvailabilityCreate]

class TeacherPreferenceBase(BaseModel):
    preference_type: str  # preferred_period, avoid_period, max_daily, preferred_day, avoid_day
    day_of_week: int | None = None
    period: int | None = None
    value: int | None = None
    weight: int = 1

class TeacherPreferenceCreate(TeacherPreferenceBase):
    pass

class TeacherPreferenceOut(TeacherPreferenceBase):
    id: int
    teacher_id: int

    class Config:
        from_attributes = True



