"""
Sri Shakthi (College) - institution seed SCAFFOLD.

STATUS: placeholder. No college data has been provided yet. Every data block
below is intentionally empty and annotated with the shape it expects. Fill the
blocks in, flip DATA_READY = True, and run again to build the institution.

Design principle - nothing is hardcoded for "college":
    The backend has one generic scheduling engine driven entirely by an
    institution's configuration. College concepts map onto the existing
    primitives, so no new engine code is needed:

        College concept        ->  Platform primitive
        ---------------------      ------------------------------
        Institution (college)  ->  School row  (institution_type="college")
        Department / Program   ->  Class  (a named group of sections)
        Year / Semester        ->  Class  (e.g. "Semester 3") or grade label
        Section / Batch        ->  Section
        Faculty                ->  Teacher
        Course / Subject       ->  Subject (weekly_hours = contact hours/credits)
        Laboratory / Practical ->  Activity or a resource-bound Subject
        Elective               ->  Subject taught to selected sections
        Shared faculty         ->  one Teacher allocated across departments
        Timetable rules        ->  scheduling_policies (all configurable)

Running while empty is safe: main() validates the (empty) structure, prints the
build plan and exits 0 WITHOUT contacting a server. Once DATA_READY is True it
builds the institution over the same REST API the school seed uses.

Usage:
    python -m uvicorn app.main:app --port 8010        # only needed when DATA_READY
    python -m app.seeds.Sri_Shakthi_seed
"""
import os
import sys
import json

import requests

BASE = os.environ.get("EDUFLOW_BASE_URL", "http://127.0.0.1:8010").rstrip("/")
ADMIN_EMAIL = os.environ.get("EDUFLOW_ADMIN_EMAIL", "admin@school.edu")
ADMIN_PASSWORD = os.environ.get("EDUFLOW_ADMIN_PASSWORD", "Admin@123")

# Set to True once the data blocks below are populated.
DATA_READY = False

# ---------------------------------------------------------------- institution
INSTITUTION = {
    "name": "Sri Shakthi Institute (College)",
    "institution_type": "college",
    "academic_year": "2026-2027",
    "periods_per_day": 8,
    "working_days": 5,
    # period_timings: [{"period": 1, "start": "09:00", "end": "09:50"}, ...]
    "period_timings": [],
    # Optional single lunch marker for documentation; the real break is derived
    # from the gap between consecutive period_timings.
    "lunch_after_period": None,
}

# ---------------------------------------------------------------- structure
# Departments / programs offered by the college.
#   e.g. [{"code": "CSE", "name": "Computer Science & Engineering"}, ...]
DEPARTMENTS: list[dict] = []

# Programs within departments (optional; use if you model UG/PG separately).
#   e.g. [{"department": "CSE", "name": "B.E CSE", "duration_years": 4}, ...]
PROGRAMS: list[dict] = []

# Years / semesters become "classes" in the platform.
#   e.g. ["Semester 1", "Semester 3", "Semester 5"]
YEARS_OR_SEMESTERS: list[str] = []

# Sections / batches per year-semester.
#   e.g. {"Semester 3": ["A", "B"], "Semester 5": ["A"]}
SECTIONS: dict[str, list[str]] = {}

# ---------------------------------------------------------------- people
# Faculty. password/email optional - a default is generated if omitted.
#   e.g. [{"name": "Dr. Rao", "email": "rao@srishakthi.edu", "department": "CSE",
#          "max_weekly_hours": 18}, ...]
FACULTY: list[dict] = []

# ---------------------------------------------------------------- academics
# Courses / subjects. weekly_hours = scheduled contact periods per week.
#   e.g. [{"name": "Data Structures", "code": "CS201", "credits": 4,
#          "weekly_hours": 4, "is_lab": False, "is_elective": False}, ...]
COURSES: list[dict] = []

# Laboratories / practicals (modelled as activities or resource-bound courses).
#   e.g. [{"name": "DS Lab", "weekly_hours": 3, "resource": "Lab-1"}, ...]
LABS: list[dict] = []

# Physical resources (labs, seminar halls) with capacity constraints.
#   e.g. [{"name": "Lab-1", "type": "lab"}, {"name": "Seminar Hall", "type": "hall"}]
RESOURCES: list[dict] = []

# Course allocation: which faculty teaches which course to which section.
#   e.g. [{"section": "Semester 3 A", "course": "CS201", "faculty": "Dr. Rao"}, ...]
ALLOCATIONS: list[dict] = []

# Faculty availability grids (hard constraints). Same shape the school uses.
#   e.g. {"Dr. Rao": {"allowed": {0: [1,2,3], ...}}}  or  {"blocked": {...}}
FACULTY_AVAILABILITY: dict[str, dict] = {}

# Fixed events -> locked slots (e.g. a common hour, mentoring).
#   e.g. [{"section": "Semester 3 A", "day": 4, "period": 8, "name": "Mentoring"}]
FIXED_EVENTS: list[dict] = []

# ---------------------------------------------------------------- rules
# All scheduling rules are configuration, never code. Fill as needed; every key
# here is already understood by the generic scheduler.
SCHEDULING_POLICIES: dict = {
    "max_consecutive_periods": 4,
    "max_daily_periods": 8,
    "double_periods_allowed": True,
    # "core_subjects": [], "min_core_per_day": None, "max_core_per_day": None,
    # "double_period_subjects": {},        # e.g. {"DS Lab": 1}
    # "subject_forbidden_periods": {},     # e.g. {"Library": [1]}
    # "single_per_day_subjects": [],       # e.g. ["Physical Education"]
}

# Validation thresholds (optional overrides of platform defaults).
VALIDATION_RULES: dict = {}


# ---------------------------------------------------------------- helpers
def _plan() -> list[str]:
    """A human-readable summary of what a populated run would create. Pure - no I/O."""
    return [
        f"institution      : {INSTITUTION['name']} (type={INSTITUTION['institution_type']})",
        f"academic year    : {INSTITUTION['academic_year']}",
        f"grid             : {INSTITUTION['periods_per_day']} periods x {INSTITUTION['working_days']} days",
        f"departments      : {len(DEPARTMENTS)}",
        f"programs         : {len(PROGRAMS)}",
        f"years/semesters  : {len(YEARS_OR_SEMESTERS)}",
        f"sections         : {sum(len(v) for v in SECTIONS.values())}",
        f"faculty          : {len(FACULTY)}",
        f"courses          : {len(COURSES)}",
        f"labs             : {len(LABS)}",
        f"resources        : {len(RESOURCES)}",
        f"allocations      : {len(ALLOCATIONS)}",
        f"fixed events     : {len(FIXED_EVENTS)}",
        f"scheduling rules : {sorted(SCHEDULING_POLICIES.keys())}",
    ]


def _validate_structure() -> list[str]:
    """Cheap consistency checks that do not need a server. Returns problems (empty = OK)."""
    problems: list[str] = []
    if INSTITUTION.get("institution_type") != "college":
        problems.append("INSTITUTION.institution_type must be 'college'")
    if not isinstance(SECTIONS, dict):
        problems.append("SECTIONS must be a dict of {year_or_semester: [section names]}")
    # Every section's year-semester must be declared.
    for ys in SECTIONS:
        if YEARS_OR_SEMESTERS and ys not in YEARS_OR_SEMESTERS:
            problems.append(f"SECTIONS references '{ys}' not in YEARS_OR_SEMESTERS")
    faculty_names = {f.get("name") for f in FACULTY}
    course_names = {c.get("name") for c in COURSES}
    for a in ALLOCATIONS:
        if a.get("faculty") not in faculty_names:
            problems.append(f"ALLOCATION references unknown faculty '{a.get('faculty')}'")
        if a.get("course") not in course_names:
            problems.append(f"ALLOCATION references unknown course '{a.get('course')}'")
    return problems


def main():
    print(f"== Sri Shakthi (College) seed ==  DATA_READY={DATA_READY}")

    problems = _validate_structure()
    if problems:
        print("\nSTRUCTURE PROBLEMS:")
        for p in problems:
            print("  -", p)
        sys.exit(1)

    print("\nBuild plan:")
    for line in _plan():
        print("  " + line)

    if not DATA_READY:
        print(
            "\nPlaceholder only - no data to build yet. This is expected and NOT an error.\n"
            "Populate the data blocks above, set DATA_READY = True, start the API server,\n"
            "then run again to create the institution."
        )
        sys.exit(0)

    # ---- populated path: build over the same REST API the school seed uses ----
    try:
        requests.get(f"{BASE}/health", timeout=5)
    except Exception:
        sys.exit(f"DATA_READY is True but the server is not reachable at {BASE}. Start uvicorn first.")

    sess = requests.Session()
    tok = sess.post(f"{BASE}/auth/login",
                    json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}).json()["access_token"]

    def api(method, path, **kw):
        h = {"Authorization": f"Bearer {tok}"}
        r = sess.request(method, f"{BASE}{path}", headers=h, timeout=600, **kw)
        if r.status_code >= 300:
            raise SystemExit(f"{method} {path} -> {r.status_code}: {r.text[:300]}")
        return r.json() if r.content else {}

    print("\n== Building college ==")
    inst = api("POST", "/schools", json={
        "name": INSTITUTION["name"],
        "periods_per_day": INSTITUTION["periods_per_day"],
        "working_days": INSTITUTION["working_days"],
    })
    sid = inst["id"]

    cfg = json.loads(api("GET", f"/schools/{sid}/config")["config"])
    cfg.update({
        "institution_type": "college",
        "school_type": "College",
        "academic_year": INSTITUTION["academic_year"],
        "period_timings": INSTITUTION["period_timings"],
        "teacher_assignment_method": "manual",
        "activities": {"enabled": bool(LABS), "list": [l["name"] for l in LABS]},
        "resources": {"enabled": bool(RESOURCES)},
        "scheduling_policies": SCHEDULING_POLICIES,
    })
    api("PUT", f"/schools/{sid}/config", json={"config": json.dumps(cfg)})

    # Courses, faculty, classes/sections, allocations, resources, labs, availability,
    # fixed events would be created here exactly as in Avinashi_GGHSS_seed.py. The
    # mapping table in this module's docstring shows the 1:1 correspondence.
    print(f"  institution #{sid} created; populate remaining builders as data arrives.")
    print(f"View: {BASE}/app/timetable.html")
    sys.exit(0)


if __name__ == "__main__":
    main()
