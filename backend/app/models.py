import enum
from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Boolean, DateTime, Date, Time, ForeignKey,
    Enum, Text, Float
)
from sqlalchemy.orm import relationship
from app.database import Base


class RoleEnum(str, enum.Enum):
    super_admin = "super_admin"
    school_admin = "school_admin"
    # Approval chain: a principal signs off leave / on-duty / swaps. A vice
    # (sub-)principal has the same approval rights so nothing stalls when the
    # principal is unavailable.
    principal = "principal"
    vice_principal = "vice_principal"
    teacher = "teacher"


class LeaveStatus(str, enum.Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"


class SwapStatus(str, enum.Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"


class School(Base):
    __tablename__ = "schools"
    id = Column(Integer, primary_key=True)
    name = Column(String(200), nullable=False)
    address = Column(String(300))
    phone = Column(String(30))
    # Timetable generation settings (additive; safe defaults preserve prior behavior)
    periods_per_day = Column(Integer, default=8, nullable=False)
    working_days = Column(Integer, default=5, nullable=False)  # 5 = Mon-Fri (day_of_week 0-4)
    created_at = Column(DateTime, default=datetime.utcnow)

    users = relationship("User", back_populates="school")


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    school_id = Column(Integer, ForeignKey("schools.id"), nullable=True)
    name = Column(String(150), nullable=False)
    email = Column(String(150), unique=True, nullable=False, index=True)
    hashed_password = Column(String(255), nullable=False)
    role = Column(Enum(RoleEnum), nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    school = relationship("School", back_populates="users")
    teacher_profile = relationship("Teacher", back_populates="user", uselist=False)


class Teacher(Base):
    __tablename__ = "teachers"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), unique=True, nullable=False)
    school_id = Column(Integer, ForeignKey("schools.id"), nullable=False)
    department = Column(String(100))
    max_weekly_hours = Column(Integer, default=30)
    teaching_group_id = Column(Integer, ForeignKey("teaching_groups.id"), nullable=True)

    user = relationship("User", back_populates="teacher_profile")
    subjects = relationship("Subject", secondary="teacher_subjects", back_populates="teachers")
    teaching_group = relationship("TeachingGroup")
    # Sections this teacher is the class teacher of (usually zero or one).
    class_teacher_of = relationship(
        "Section", back_populates="class_teacher", foreign_keys="Section.class_teacher_id"
    )



class TeacherSubject(Base):
    __tablename__ = "teacher_subjects"
    teacher_id = Column(Integer, ForeignKey("teachers.id"), primary_key=True)
    subject_id = Column(Integer, ForeignKey("subjects.id"), primary_key=True)


class Class(Base):
    __tablename__ = "classes"
    id = Column(Integer, primary_key=True)
    school_id = Column(Integer, ForeignKey("schools.id"), nullable=False)
    name = Column(String(50), nullable=False)

    sections = relationship("Section", back_populates="class_")


class Section(Base):
    __tablename__ = "sections"
    id = Column(Integer, primary_key=True)
    class_id = Column(Integer, ForeignKey("classes.id"), nullable=False)
    name = Column(String(50), nullable=False)
    # Instruction medium, e.g. "English" / "Tamil". Validated against the school's
    # configured mediums list when that module is enabled; free-form otherwise.
    medium = Column(String(50), nullable=True)
    # Administrative owner of the section. Does not constrain the scheduler.
    class_teacher_id = Column(Integer, ForeignKey("teachers.id"), nullable=True)

    class_ = relationship("Class", back_populates="sections")
    class_teacher = relationship(
        "Teacher", foreign_keys=[class_teacher_id], back_populates="class_teacher_of"
    )


class Subject(Base):
    __tablename__ = "subjects"
    id = Column(Integer, primary_key=True)
    school_id = Column(Integer, ForeignKey("schools.id"), nullable=False)
    name = Column(String(100), nullable=False)
    weekly_hours = Column(Integer, default=1)
    # Optional: subject requires a specific resource (e.g. a Lab) whenever scheduled
    resource_id = Column(Integer, ForeignKey("resources.id"), nullable=True)

    teachers = relationship("Teacher", secondary="teacher_subjects", back_populates="subjects")


class Activity(Base):
    __tablename__ = "activities"
    id = Column(Integer, primary_key=True)
    school_id = Column(Integer, ForeignKey("schools.id"), nullable=False)
    name = Column(String(100), nullable=False)
    weekly_hours = Column(Integer, default=1)
    # Optional: activity requires a specific resource (e.g. a Ground/Hall)
    resource_id = Column(Integer, ForeignKey("resources.id"), nullable=True)


class Resource(Base):
    __tablename__ = "resources"
    id = Column(Integer, primary_key=True)
    school_id = Column(Integer, ForeignKey("schools.id"), nullable=False)
    name = Column(String(100), nullable=False)
    type = Column(String(50))
    capacity = Column(Integer)


class Timetable(Base):
    """Layer 1: Master Timetable. One row = one (section, day, period) slot,
    holding either a subject lesson (subject_id + teacher_id set) or an
    activity (activity_id set, subject_id/teacher_id null). Generated by the
    OR-Tools CP-SAT solver; admins may lock individual rows so future
    regenerations leave them untouched."""
    __tablename__ = "timetables"
    id = Column(Integer, primary_key=True)
    school_id = Column(Integer, ForeignKey("schools.id"), nullable=False)
    section_id = Column(Integer, ForeignKey("sections.id"), nullable=False)
    subject_id = Column(Integer, ForeignKey("subjects.id"), nullable=True)
    teacher_id = Column(Integer, ForeignKey("teachers.id"), nullable=True)
    activity_id = Column(Integer, ForeignKey("activities.id"), nullable=True)
    resource_id = Column(Integer, ForeignKey("resources.id"), nullable=True)
    day_of_week = Column(Integer, nullable=False)
    period = Column(Integer, nullable=False)
    is_locked = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    section = relationship("Section")
    subject = relationship("Subject")
    teacher = relationship("Teacher")
    activity = relationship("Activity")
    resource = relationship("Resource")


class Leave(Base):
    __tablename__ = "leaves"
    id = Column(Integer, primary_key=True)
    teacher_id = Column(Integer, ForeignKey("teachers.id"), nullable=False)
    school_id = Column(Integer, ForeignKey("schools.id"), nullable=False)
    date = Column(Date, nullable=False)
    # Additive (Phase 4): multi-day leave support, admin decision trail.
    end_date = Column(Date, nullable=True)
    reason = Column(Text)
    status = Column(Enum(LeaveStatus), default=LeaveStatus.pending)
    decision_note = Column(Text, nullable=True)
    reviewed_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    reviewed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    teacher = relationship("Teacher")


class OnDutyStatus(str, enum.Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"
    cancelled = "cancelled"


class OnDuty(Base):
    """Teacher is IN school but cannot take their classes (exam duty, office work,
    inspection, training, ...). Attendance still counts as Present (yellow on the
    calendar), but the affected periods get substitutes just like a leave.

    start_period/end_period are inclusive. Leaving both NULL means the whole day.
    Like Leave, this is Layer 2: the Master Timetable is never modified."""
    __tablename__ = "on_duty"
    id = Column(Integer, primary_key=True)
    teacher_id = Column(Integer, ForeignKey("teachers.id"), nullable=False)
    school_id = Column(Integer, ForeignKey("schools.id"), nullable=False)
    date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=True)          # null = single day
    start_period = Column(Integer, nullable=True)   # null = whole day
    end_period = Column(Integer, nullable=True)
    duty_type = Column(String(60), nullable=False)
    description = Column(Text, nullable=True)
    location = Column(String(150), nullable=True)
    status = Column(Enum(OnDutyStatus), default=OnDutyStatus.pending, nullable=False)
    requested_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    assigned_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    reviewed_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    reviewed_at = Column(DateTime, nullable=True)
    decision_note = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    teacher = relationship("Teacher")


class Substitution(Base):
    __tablename__ = "substitutions"
    id = Column(Integer, primary_key=True)
    # Exactly one of leave_id / on_duty_id is set - a cover is raised either by an
    # approved leave (teacher absent) or an approved on-duty (teacher present but
    # occupied elsewhere).
    leave_id = Column(Integer, ForeignKey("leaves.id"), nullable=True)
    on_duty_id = Column(Integer, ForeignKey("on_duty.id"), nullable=True)
    timetable_id = Column(Integer, ForeignKey("timetables.id"), nullable=False)
    substitute_teacher_id = Column(Integer, ForeignKey("teachers.id"), nullable=False)
    date = Column(Date, nullable=False)
    # Additive (Phase 4): how the match was made, plain-English reason, and
    # who assigned it (null = auto engine, set = manual admin assignment).
    method = Column(String(30), nullable=True)
    reason = Column(Text, nullable=True)
    assigned_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Ranked-queue support: which rank of the candidate queue is currently serving,
    # and why the previous holder stepped aside.
    rank = Column(Integer, nullable=True)
    score = Column(Integer, nullable=True)          # 0-100 suitability
    decline_reason = Column(Text, nullable=True)

    leave = relationship("Leave")
    on_duty = relationship("OnDuty")
    timetable = relationship("Timetable")
    substitute_teacher = relationship("Teacher")


class CandidateStatus(str, enum.Enum):
    assigned = "assigned"    # currently covering (rank 1 of the live queue)
    backup = "backup"        # waiting in the queue
    declined = "declined"    # stepped aside with a valid reason
    superseded = "superseded"  # queue rebuilt / cover released


class SubstituteCandidate(Base):
    """The ranked substitute queue for ONE slot on ONE date.

    The engine does not pick a single teacher and stop - it scores every eligible
    teacher and stores the whole ranked list. Rank 1 is auto-assigned; the rest wait
    as backups. If the assigned teacher declines (with a valid reason - a free period
    is NOT one), the next rank is promoted automatically.

    The queue is readable by every teacher, so substitution load is transparent."""
    __tablename__ = "substitute_candidates"
    id = Column(Integer, primary_key=True)
    timetable_id = Column(Integer, ForeignKey("timetables.id"), nullable=False)
    date = Column(Date, nullable=False)
    teacher_id = Column(Integer, ForeignKey("teachers.id"), nullable=False)
    rank = Column(Integer, nullable=False)
    score = Column(Integer, nullable=False)         # 0-100
    method = Column(String(30), nullable=True)      # same_subject / available / ...
    reason = Column(Text, nullable=True)
    status = Column(Enum(CandidateStatus), default=CandidateStatus.backup, nullable=False)
    decline_reason = Column(Text, nullable=True)
    leave_id = Column(Integer, ForeignKey("leaves.id"), nullable=True)
    on_duty_id = Column(Integer, ForeignKey("on_duty.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    teacher = relationship("Teacher")
    timetable = relationship("Timetable")


class Swap(Base):
    """Layer 2 overlay (Phase 5), same pattern as Substitution: on `date`
    only, the two Timetable slots' effective content (subject/teacher/
    activity/resource) is shown swapped with each other. Layer 1
    (Timetable rows) is never touched. See GET /substitutions/schedule for
    the resulting effective schedule, which overlays both Substitutions
    and approved Swaps for the requested date."""
    __tablename__ = "swaps"
    id = Column(Integer, primary_key=True)
    timetable_id_a = Column(Integer, ForeignKey("timetables.id"), nullable=False)
    timetable_id_b = Column(Integer, ForeignKey("timetables.id"), nullable=False)
    date = Column(Date, nullable=False)
    approved_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    # Additive (Phase 5): approval workflow, mirroring Leave.
    school_id = Column(Integer, ForeignKey("schools.id"), nullable=True)
    status = Column(Enum(SwapStatus), default=SwapStatus.pending, nullable=False)
    requested_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    reason = Column(Text, nullable=True)
    decision_note = Column(Text, nullable=True)
    reviewed_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    reviewed_at = Column(DateTime, nullable=True)

    # Cross-day exchange: `date` is side A's date, `date_b` is side B's. NULL means
    # "same day as A", which is exactly how every pre-existing same-day swap behaves,
    # so this is backward compatible. On date A, slot A shows slot B's lesson; on
    # date B, slot B shows slot A's. Both remain a read-time overlay - the Master
    # Timetable is never modified.
    date_b = Column(Date, nullable=True)

    # Two-step consent: the TARGET teacher accepts/declines first, then an
    # admin/principal approves. None = not yet answered.
    target_accepted = Column(Boolean, nullable=True)
    target_note = Column(Text, nullable=True)
    target_reviewed_at = Column(DateTime, nullable=True)

    timetable_a = relationship("Timetable", foreign_keys=[timetable_id_a])
    timetable_b = relationship("Timetable", foreign_keys=[timetable_id_b])


class Exam(Base):
    __tablename__ = "exams"
    id = Column(Integer, primary_key=True)
    school_id = Column(Integer, ForeignKey("schools.id"), nullable=False)
    subject_id = Column(Integer, ForeignKey("subjects.id"), nullable=False)
    section_id = Column(Integer, ForeignKey("sections.id"), nullable=False)
    resource_id = Column(Integer, ForeignKey("resources.id"), nullable=True)
    invigilator_id = Column(Integer, ForeignKey("teachers.id"), nullable=True)
    date = Column(Date, nullable=False)
    start_time = Column(Time, nullable=False)
    end_time = Column(Time, nullable=False)

    # Additive (Phase 6): relationships for eager-loading in exams.py;
    # the columns above already existed from the original schema.
    subject = relationship("Subject")
    section = relationship("Section")
    resource = relationship("Resource")
    invigilator = relationship("Teacher")


class Notification(Base):
    __tablename__ = "notifications"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    message = Column(Text, nullable=False)
    is_read = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    action = Column(String(150), nullable=False)
    details = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)


class SchoolConfig(Base):
    __tablename__ = "school_configs"
    school_id = Column(Integer, ForeignKey("schools.id"), primary_key=True)
    config = Column(Text, nullable=False)  # JSON-encoded configuration string
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class SubjectAssignment(Base):
    __tablename__ = "subject_assignments"
    id = Column(Integer, primary_key=True)
    school_id = Column(Integer, ForeignKey("schools.id"), nullable=False)
    section_id = Column(Integer, ForeignKey("sections.id"), nullable=False)
    subject_id = Column(Integer, ForeignKey("subjects.id"), nullable=False)
    teacher_id = Column(Integer, ForeignKey("teachers.id"), nullable=True)  # Nullable for hybrid mode
    weekly_hours_override = Column(Integer, nullable=True)  # Per-section override; NULL = use subject.weekly_hours

    section = relationship("Section")
    subject = relationship("Subject")
    teacher = relationship("Teacher")


class TeacherAvailability(Base):
    """Per-teacher, per-(day, period) availability slots.
    is_available=False means the teacher is blocked from that slot."""
    __tablename__ = "teacher_availability"
    id = Column(Integer, primary_key=True)
    teacher_id = Column(Integer, ForeignKey("teachers.id"), nullable=False)
    day_of_week = Column(Integer, nullable=False)  # 0=Mon, 1=Tue, ...
    period = Column(Integer, nullable=False)
    is_available = Column(Boolean, default=True)

    teacher = relationship("Teacher")


class TeacherPreference(Base):
    """Soft scheduling preferences for teachers.
    Types: preferred_period, avoid_period, max_daily, preferred_day, avoid_day"""
    __tablename__ = "teacher_preferences"
    id = Column(Integer, primary_key=True)
    teacher_id = Column(Integer, ForeignKey("teachers.id"), nullable=False)
    preference_type = Column(String(50), nullable=False)
    day_of_week = Column(Integer, nullable=True)
    period = Column(Integer, nullable=True)
    value = Column(Integer, nullable=True)  # e.g. max_daily = 5
    weight = Column(Integer, default=1)  # soft constraint weight (1-10)

    teacher = relationship("Teacher")


class TeachingGroup(Base):
    __tablename__ = "teaching_groups"
    id = Column(Integer, primary_key=True)
    school_id = Column(Integer, ForeignKey("schools.id"), nullable=False)
    name = Column(String(100), nullable=False)
    allowed_grades = Column(Text, nullable=False)  # Comma-separated grades


class CalendarEvent(Base):
    __tablename__ = "calendar_events"
    id = Column(Integer, primary_key=True)
    school_id = Column(Integer, ForeignKey("schools.id"), nullable=False)
    title = Column(String(200), nullable=False)
    date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=True)
    type = Column(String(50), nullable=False)  # holiday, exam_week, special_event
    is_holiday = Column(Boolean, default=True)


class TimetableVersion(Base):
    __tablename__ = "timetable_versions"
    id = Column(Integer, primary_key=True)
    school_id = Column(Integer, ForeignKey("schools.id"), nullable=False)
    name = Column(String(100), nullable=False)
    status = Column(String(50), default="draft", nullable=False)  # "draft", "under_review", "approved", "published", "archived"
    created_at = Column(DateTime, default=datetime.utcnow)
    
    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    published_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    published_time = Column(DateTime, nullable=True)
    reason = Column(Text, nullable=True)
    generation_policy = Column(String(100), nullable=True)
    academic_year = Column(String(50), nullable=True)
    term = Column(String(50), nullable=True)
    semester = Column(String(50), nullable=True)

    slots = relationship("TimetableVersionSlot", back_populates="version", cascade="all, delete-orphan")
    created_by = relationship("User", foreign_keys=[created_by_id])
    published_by = relationship("User", foreign_keys=[published_by_id])


class TimetableVersionSlot(Base):
    __tablename__ = "timetable_version_slots"
    id = Column(Integer, primary_key=True)
    version_id = Column(Integer, ForeignKey("timetable_versions.id"), nullable=False)
    section_id = Column(Integer, ForeignKey("sections.id"), nullable=False)
    subject_id = Column(Integer, ForeignKey("subjects.id"), nullable=True)
    teacher_id = Column(Integer, ForeignKey("teachers.id"), nullable=True)
    activity_id = Column(Integer, ForeignKey("activities.id"), nullable=True)
    resource_id = Column(Integer, ForeignKey("resources.id"), nullable=True)
    day_of_week = Column(Integer, nullable=False)
    period = Column(Integer, nullable=False)
    is_locked = Column(Boolean, default=False)

    version = relationship("TimetableVersion", back_populates="slots")
    section = relationship("Section")
    subject = relationship("Subject")
    teacher = relationship("Teacher")
    activity = relationship("Activity")
    resource = relationship("Resource")

