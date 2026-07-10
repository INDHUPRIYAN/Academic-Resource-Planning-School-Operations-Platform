"""
End-to-end test for Phase 7 (Reports), hitting a live uvicorn instance over
HTTP exactly like the frontend would. Same approach as test_leaves_ui.py /
test_swaps_ui.py / test_exams_ui.py.

Builds a small school (classes/sections/subjects/resources/teachers),
generates a real master timetable via /timetables/generate (OR-Tools),
takes/approves a leave to get real Substitution coverage data, schedules an
exam, then exercises all five report JSON endpoints and their PDF/Excel
exports.

Run: start the server first (see README), then:
    python test_reports_ui.py
"""
import sys
import random

import requests

BASE = "http://localhost:8000"


def req(method, path, token=None, **kw):
    headers = kw.pop("headers", {})
    if token:
        headers["Authorization"] = f"Bearer {token}"
    r = requests.request(method, f"{BASE}{path}", headers=headers, **kw)
    return r


def check(cond, msg):
    if not cond:
        print(f"FAIL: {msg}")
        sys.exit(1)
    print(f"OK: {msg}")


def main():
    suffix = random.randint(10000, 99999)

    from app.database import SessionLocal, Base, engine
    from app import models
    from app.auth import hash_password
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    sa_email = f"reptest.superadmin.{suffix}@example.com"
    sa = models.User(name="ReportTest SuperAdmin", email=sa_email,
                      hashed_password=hash_password("pass1234"), role=models.RoleEnum.super_admin)
    db.add(sa)
    db.commit()
    db.close()

    r = req("POST", "/auth/login", json={"email": sa_email, "password": "pass1234"})
    check(r.status_code == 200, "super_admin login")
    sa_token = r.json()["access_token"]

    # --- school, classes/sections, subjects, resources, teachers ---
    r = req("POST", "/schools", token=sa_token, json={"name": f"Report Test School {suffix}", "periods_per_day": 6, "working_days": 5})
    check(r.status_code == 201, "create school")
    school_id = r.json()["id"]

    r = req("POST", "/classes", token=sa_token, json={"school_id": school_id, "name": "Grade 9"})
    check(r.status_code == 201, "create class")
    class_id = r.json()["id"]

    r = req("POST", "/sections", token=sa_token, json={"class_id": class_id, "name": "A"})
    check(r.status_code == 201, "create section")
    section_id = r.json()["id"]

    r = req("POST", "/resources", token=sa_token, json={"school_id": school_id, "name": "Lab 1", "type": "lab", "capacity": 30})
    check(r.status_code == 201, "create resource")
    resource_id = r.json()["id"]

    subject_ids = []
    for name, hours in [("Math", 4), ("Science", 3)]:
        r = req("POST", "/subjects", token=sa_token, json={"school_id": school_id, "name": name, "weekly_hours": hours})
        check(r.status_code == 201, f"create subject {name}")
        subject_ids.append(r.json()["id"])

    teacher_ids = []
    teacher_emails = []
    for i in range(2):
        email = f"reptest.t{i}.{suffix}@example.com"
        teacher_emails.append(email)
        r = req("POST", "/teachers", token=sa_token, json={
            "school_id": school_id, "name": f"Report Teacher {i}", "email": email, "password": "pass1234",
            "department": "Science", "max_weekly_hours": 20, "subject_ids": subject_ids,
        })
        check(r.status_code == 201, f"create teacher {i}")
        teacher_ids.append(r.json()["id"])

    r = req("POST", "/auth/login", json={"email": sa_email, "password": "pass1234"})
    admin_token = r.json()["access_token"]

    r = req("POST", "/auth/login", json={"email": teacher_emails[0], "password": "pass1234"})
    check(r.status_code == 200, "teacher login")
    teacher_token = r.json()["access_token"]

    # --- generate a real master timetable ---
    r = req("POST", "/timetables/generate", token=sa_token, json={"school_id": school_id, "time_limit_seconds": 10})
    check(r.status_code == 200, f"generate timetable ({r.json().get('message', '')})")

    r = req("GET", f"/timetables/teacher/{teacher_ids[0]}", token=sa_token)
    check(r.status_code == 200 and len(r.json()["slots"]) > 0, "teacher 0 has scheduled slots")
    slots = r.json()["slots"]
    target_day = slots[0]["day_of_week"]
    import datetime
    base_date = datetime.date(2026, 7, 6)  # Monday
    leave_date = base_date + datetime.timedelta(days=target_day)

    # --- take + approve a leave, so leave-summary has real coverage data ---
    r = req("POST", "/leaves", token=teacher_token, json={"date": str(leave_date), "reason": "Report test leave"})
    check(r.status_code == 201, "teacher applies for leave")
    leave_id = r.json()["id"]
    r = req("POST", f"/leaves/{leave_id}/approve", token=sa_token, json={})
    check(r.status_code == 200, "admin approves leave")

    # --- schedule an exam using the resource, for resource-usage coverage ---
    r = req("POST", "/exams", token=sa_token, json={
        "subject_id": subject_ids[0], "section_id": section_id, "resource_id": resource_id,
        "date": "2026-08-10", "start_time": "09:00:00", "end_time": "10:00:00",
    })
    check(r.status_code == 201, "schedule an exam using the lab resource")

    # ============================================================ role check
    r = req("GET", f"/reports/teacher-workload?school_id={school_id}", token=teacher_token)
    check(r.status_code == 403, "teacher (non-admin) cannot access reports")

    # ============================================================ super_admin without school_id
    r = req("GET", "/reports/teacher-workload", token=sa_token)
    check(r.status_code == 400, "super_admin without school_id is rejected (400)")

    # ============================================================ Teacher Workload
    r = req("GET", f"/reports/teacher-workload?school_id={school_id}", token=admin_token)
    check(r.status_code == 200, "teacher-workload JSON")
    data = r.json()
    check(len(data["teachers"]) == 2, "teacher-workload lists both teachers")
    t0 = next(t for t in data["teachers"] if t["teacher_id"] == teacher_ids[0])
    check(t0["scheduled_periods"] > 0, "teacher 0 shows nonzero scheduled_periods")
    check(t0["utilization_pct"] is not None, "teacher 0 has a utilization_pct")

    for fmt in ("pdf", "xlsx"):
        r = req("GET", f"/reports/export/teacher-workload?school_id={school_id}&format={fmt}", token=admin_token)
        check(r.status_code == 200 and len(r.content) > 200, f"teacher-workload export ({fmt}) returns a real file")
        check(r.headers.get("content-type", "").startswith("application/"), f"teacher-workload export ({fmt}) has correct content-type")

    # ============================================================ Subject Coverage
    r = req("GET", f"/reports/subject-coverage?school_id={school_id}", token=admin_token)
    check(r.status_code == 200, "subject-coverage JSON")
    data = r.json()
    check(len(data["rows"]) > 0, "subject-coverage has rows")
    math_row = next((row for row in data["rows"] if row["subject_name"] == "Math"), None)
    check(math_row is not None, "subject-coverage includes Math")
    check(math_row["required_weekly_hours"] == 4, "Math required_weekly_hours matches what was configured")

    for fmt in ("pdf", "xlsx"):
        r = req("GET", f"/reports/export/subject-coverage?school_id={school_id}&format={fmt}", token=admin_token)
        check(r.status_code == 200 and len(r.content) > 200, f"subject-coverage export ({fmt}) returns a real file")

    # ============================================================ Resource Usage
    r = req("GET", f"/reports/resource-usage?school_id={school_id}", token=admin_token)
    check(r.status_code == 200, "resource-usage JSON")
    data = r.json()
    lab = next((res for res in data["resources"] if res["resource_id"] == resource_id), None)
    check(lab is not None, "resource-usage includes Lab 1")
    check(lab["exam_bookings"] == 1, "Lab 1 shows exam_bookings == 1")

    for fmt in ("pdf", "xlsx"):
        r = req("GET", f"/reports/export/resource-usage?school_id={school_id}&format={fmt}", token=admin_token)
        check(r.status_code == 200 and len(r.content) > 200, f"resource-usage export ({fmt}) returns a real file")

    # ============================================================ Leave Summary
    r = req("GET", f"/reports/leave-summary?school_id={school_id}&start_date=2026-07-01&end_date=2026-07-31", token=admin_token)
    check(r.status_code == 200, "leave-summary JSON")
    data = r.json()
    check(data["by_status"]["approved"] == 1, "leave-summary shows 1 approved leave")
    check(data["slots_needing_coverage"] > 0, "leave-summary shows slots_needing_coverage > 0")
    check(data["coverage_rate_pct"] is not None, "leave-summary computes a coverage_rate_pct")

    r = req("GET", f"/reports/leave-summary?school_id={school_id}&start_date=2026-07-15&end_date=2026-07-31", token=admin_token)
    check(r.status_code == 200 and r.json()["by_status"]["approved"] == 0, "leave-summary respects date range (leave outside range excluded)")

    for fmt in ("pdf", "xlsx"):
        r = req("GET", f"/reports/export/leave-summary?school_id={school_id}&format={fmt}", token=admin_token)
        check(r.status_code == 200 and len(r.content) > 200, f"leave-summary export ({fmt}) returns a real file")

    # ============================================================ Timetables
    r = req("GET", "/reports/timetable", token=admin_token)
    check(r.status_code == 400, "timetable report with neither section_id nor teacher_id is rejected (400)")

    r = req("GET", f"/reports/timetable?section_id={section_id}", token=admin_token)
    check(r.status_code == 200, "timetable report by section_id")
    check(len(r.json()["grid"]) > 0, "timetable report grid has rows")

    r = req("GET", f"/reports/timetable?teacher_id={teacher_ids[0]}", token=admin_token)
    check(r.status_code == 200, "timetable report by teacher_id")

    for fmt in ("pdf", "xlsx"):
        r = req("GET", f"/reports/export/timetable?section_id={section_id}&format={fmt}", token=admin_token)
        check(r.status_code == 200 and len(r.content) > 200, f"timetable export by section ({fmt}) returns a real file")

    r = req("GET", f"/reports/export/timetable?section_id=999999&format=pdf", token=admin_token)
    check(r.status_code == 404, "timetable export for a nonexistent section is 404")

    print("\nALL PHASE 7 (REPORTS) TESTS PASSED")


if __name__ == "__main__":
    main()
