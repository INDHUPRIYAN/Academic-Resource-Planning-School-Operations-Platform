import time
import math
from sqlalchemy.orm import Session, joinedload
from app import models

# In-memory validation cache mapping school_id -> (timestamp, report_dict)
_VALIDATION_CACHE = {}

def invalidate_cache(school_id: int):
    if school_id in _VALIDATION_CACHE:
        del _VALIDATION_CACHE[school_id]

class ValidationRegistry:
    def __init__(self):
        # Category lists
        self.categories = ["Configuration", "Assignments", "Teachers", "Resources", "Calendar", "Policies"]
        self._validators = {cat: [] for cat in self.categories}

    def register(self, category: str, validator_func):
        if category not in self._validators:
            raise ValueError(f"Invalid category: {category}")
        self._validators[category].append(validator_func)

    def validate(self, school_id: int, db: Session, bypass_cache: bool = False) -> dict:
        # Check cache
        if not bypass_cache and school_id in _VALIDATION_CACHE:
            return _VALIDATION_CACHE[school_id]

        school = db.query(models.School).filter(models.School.id == school_id).first()
        if not school:
            return {"error": "School not found"}

        # Gather data
        classes = db.query(models.Class).filter(models.Class.school_id == school_id).all()
        sections = db.query(models.Section).join(models.Class).filter(models.Class.school_id == school_id).all()
        subjects = db.query(models.Subject).filter(models.Subject.school_id == school_id).all()
        teachers = db.query(models.Teacher).options(joinedload(models.Teacher.subjects), joinedload(models.Teacher.user)).filter(models.Teacher.school_id == school_id).all()
        resources = db.query(models.Resource).filter(models.Resource.school_id == school_id).all()
        assignments = db.query(models.SubjectAssignment).filter(models.SubjectAssignment.school_id == school_id).all()
        events = db.query(models.CalendarEvent).filter(models.CalendarEvent.school_id == school_id).all()
        config_row = db.query(models.SchoolConfig).filter(models.SchoolConfig.school_id == school_id).first()
        import json
        config = json.loads(config_row.config) if config_row else {}

        context = {
            "school": school,
            "classes": classes,
            "sections": sections,
            "subjects": subjects,
            "teachers": teachers,
            "resources": resources,
            "assignments": assignments,
            "events": events,
            "config": config,
        }

        # Run all validators
        category_reports = {}
        overall_score = 100
        category_scores = {}

        for cat in self.categories:
            items = []
            for val_func in self._validators[cat]:
                try:
                    items.extend(val_func(context, db))
                except Exception as e:
                    items.append({
                        "severity": "Critical Error",
                        "message": f"Validator failed to execute: {str(e)}",
                        "details": f"Function: {val_func.__name__}"
                    })

            # Calculate category score
            cat_score = 100
            for item in items:
                if item["severity"] == "Critical Error":
                    cat_score -= 15
                elif item["severity"] == "Warning":
                    cat_score -= 5
            cat_score = max(0, min(100, cat_score))
            category_scores[cat] = cat_score

            category_reports[cat] = {
                "score": cat_score,
                "items": items
            }

        # Overall score is the average of category scores
        overall_score = int(sum(category_scores.values()) / len(self.categories))

        # Compute Quality Scores (Item 9)
        quality_score = compute_scheduler_quality(school_id, context, db)

        report = {
            "school_id": school_id,
            "readiness_score": overall_score,
            "category_scores": category_scores,
            "categories": category_reports,
            "quality_score": quality_score,
            "ready_to_generate": overall_score >= 50,
            "ready_to_publish": overall_score >= 80,
            "timestamp": time.time()
        }

        # Cache report
        _VALIDATION_CACHE[school_id] = report
        return report

# Initialize dynamic validation registry
validation_registry = ValidationRegistry()

# ----------------- Core Validators -----------------

def config_validator(ctx, db):
    items = []
    # Missing main configuration check
    if not ctx["config"]:
        items.append({
            "severity": "Critical Error",
            "message": "School configuration has not been set up.",
            "details": "Please run the setup wizard or save configuration details in the Config Editor."
        })
    # Dependency: Leaves enabled but Calendar disabled?
    # Or verify periods per day
    if ctx["school"].periods_per_day < 3:
        items.append({
            "severity": "Warning",
            "message": "Fewer than 3 periods per day configured.",
            "details": "Usually schools configure 5 to 9 periods per day."
        })
    return items

def assignments_validator(ctx, db):
    items = []
    # Missing subjects on class/section
    if ctx["sections"] and not ctx["assignments"]:
        items.append({
            "severity": "Critical Error",
            "message": "No subjects assigned to any section.",
            "details": "Configure assignments in the Assignments or Setup Wizard page."
        })
    # Check section overload
    total_slots = ctx["school"].working_days * ctx["school"].periods_per_day
    for sec in ctx["sections"]:
        sec_subjs = [ass for ass in ctx["assignments"] if ass.section_id == sec.id]
        if not sec_subjs:
            items.append({
                "severity": "Warning",
                "message": f"Section '{sec.class_.name} {sec.name}' has no subjects assigned.",
                "details": "It will remain completely free in the timetable."
            })
            continue
        subj_hours = sum(ass.subject.weekly_hours for ass in sec_subjs if ass.subject)
        if subj_hours > total_slots:
            items.append({
                "severity": "Critical Error",
                "message": f"Section '{sec.class_.name} {sec.name}' hours exceed capacity.",
                "details": f"Assigned hours ({subj_hours} hrs) exceed total weekly slots ({total_slots})."
            })
    return items

def teachers_validator(ctx, db):
    items = []
    # Missing subjects on teachers
    for t in ctx["teachers"]:
        if not t.subjects:
            items.append({
                "severity": "Warning",
                "message": f"Teacher '{t.user.name}' has no subjects assigned in their profile.",
                "details": "They cannot be scheduled for lessons automatically."
            })
    # Teacher overload check
    teacher_hours = {}
    for ass in ctx["assignments"]:
        if ass.teacher_id and ass.subject:
            teacher_hours[ass.teacher_id] = teacher_hours.get(ass.teacher_id, 0) + ass.subject.weekly_hours
    
    for t in ctx["teachers"]:
        hours = teacher_hours.get(t.id, 0)
        if hours > t.max_weekly_hours:
            items.append({
                "severity": "Warning",
                "message": f"Teacher '{t.user.name}' workload limit exceeded.",
                "details": f"Scheduled assignments total {hours} hours, but limit is {t.max_weekly_hours} hours."
            })
    return items

def resources_validator(ctx, db):
    items = []
    resources_enabled = ctx["config"].get("resources", {}).get("enabled", True)
    if resources_enabled:
        # Check if subjects require a resource but no resource of that type exists
        for subj in ctx["subjects"]:
            if subj.resource_id:
                res_match = next((r for r in ctx["resources"] if r.id == subj.resource_id), None)
                if not res_match:
                    items.append({
                        "severity": "Critical Error",
                        "message": f"Resource required by Subject '{subj.name}' is missing.",
                        "details": "The resource was deleted or mismatch exists."
                    })
    return items

def calendar_validator(ctx, db):
    items = []
    # Missing calendar setup or checks for holiday dates
    if not ctx["events"]:
        items.append({
            "severity": "Information",
            "message": "No academic calendar events or holidays defined.",
            "details": "Add events in the Calendar tab so the timetable scheduler can respect holidays."
        })
    return items

def policies_validator(ctx, db):
    items = []
    # Suggesting preferred policies
    policies = ctx["config"].get("scheduling_policies", {})
    if not policies.get("max_consecutive_periods"):
        items.append({
            "severity": "Suggestion",
            "message": "Enable 'Max Consecutive Periods' policy.",
            "details": "Helps avoid teachers taking back-to-back classes for too long."
        })
    return items

# Register Core Validators
validation_registry.register("Configuration", config_validator)
validation_registry.register("Assignments", assignments_validator)
validation_registry.register("Teachers", teachers_validator)
validation_registry.register("Resources", resources_validator)
validation_registry.register("Calendar", calendar_validator)
validation_registry.register("Policies", policies_validator)

# ----------------- Quality score helper -----------------

def compute_scheduler_quality(school_id: int, ctx: dict, db: Session) -> dict:
    slots = db.query(models.Timetable).filter(models.Timetable.school_id == school_id).all()
    if not slots:
        return {
            "overall_quality": 0,
            "teacher_balance": 0,
            "resource_utilization": 0,
            "subject_distribution": 0
        }

    # 1. Teacher Balance Score
    # Measure variance in teacher assigned periods
    teacher_loads = {}
    for t in ctx["teachers"]:
        teacher_loads[t.id] = 0
    for s in slots:
        if s.teacher_id:
            teacher_loads[s.teacher_id] = teacher_loads.get(s.teacher_id, 0) + 1
    
    loads = list(teacher_loads.values())
    if loads:
        mean_load = sum(loads) / len(loads)
        variance = sum((x - mean_load) ** 2 for x in loads) / len(loads)
        std_dev = math.sqrt(variance)
        # Higher balance score when std_dev is lower (meaning loads are balanced)
        tb_score = max(0, min(100, int(100 - (std_dev * 10))))
    else:
        tb_score = 100

    # 2. Resource Utilization Score
    # Percentage of resource slots booked vs capacity
    res_bookings = 0
    total_res_capacity = len(ctx["resources"]) * ctx["school"].periods_per_day * ctx["school"].working_days
    for s in slots:
        if s.resource_id:
            res_bookings += 1
            
    if total_res_capacity > 0:
        ru_score = min(100, int((res_bookings / total_res_capacity) * 100))
    else:
        ru_score = 100  # Default if no resources are needed

    # 3. Subject Distribution Score
    # How well we distribute subjects (consecutive limit violations)
    consec_clashes = 0
    # Group slots by (section, day)
    section_day_slots = {}
    for s in slots:
        key = (s.section_id, s.day_of_week)
        section_day_slots.setdefault(key, []).append(s)

    for key, day_slots in section_day_slots.items():
        day_slots.sort(key=lambda x: x.period)
        last_subj = None
        consec_count = 0
        for s in day_slots:
            if s.subject_id:
                if s.subject_id == last_subj:
                    consec_count += 1
                    if consec_count > 2:
                        consec_clashes += 1
                else:
                    last_subj = s.subject_id
                    consec_count = 1
            else:
                last_subj = None
                consec_count = 0
                
    sd_score = max(0, min(100, int(100 - (consec_clashes * 5))))

    overall_quality = int((tb_score + ru_score + sd_score) / 3)

    return {
        "overall_quality": overall_quality,
        "teacher_balance": tb_score,
        "resource_utilization": ru_score,
        "subject_distribution": sd_score
    }
