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

    # 1. Bootstrap super_admin user
    from app.database import SessionLocal, Base, engine
    from app import models
    from app.auth import hash_password
    
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    sa_email = f"valtest.superadmin.{suffix}@example.com"
    sa = models.User(name="ValTest SuperAdmin", email=sa_email,
                      hashed_password=hash_password("pass1234"), role=models.RoleEnum.super_admin)
    db.add(sa)
    db.commit()
    db.close()

    # 2. Login
    r = req("POST", "/auth/login", json={"email": sa_email, "password": "pass1234"})
    check(r.status_code == 200, "super_admin login")
    sa_token = r.json()["access_token"]

    # 3. Create school
    r = req("POST", "/schools", token=sa_token, json={"name": f"Val Test School {suffix}", "periods_per_day": 5, "working_days": 5})
    check(r.status_code == 201, "create school")
    school_id = r.json()["id"]

    # 4. Check initial validation (should have blocker errors because no classes/sections/subjects are configured)
    r = req("GET", f"/validation/school/{school_id}", token=sa_token)
    check(r.status_code == 200, f"get initial validation report (status={r.status_code}, response={r.text})")
    data = r.json()
    check(data["readiness_score"] < 100, "readiness score shows blocker errors")
    check(len(data["errors"]) > 0, "errors list contains structural errors")

    # 5. Add Class & Section
    r = req("POST", "/classes", token=sa_token, json={"school_id": school_id, "name": "Grade 10"})
    check(r.status_code == 201, "create class")
    class_id = r.json()["id"]

    r = req("POST", "/sections", token=sa_token, json={"class_id": class_id, "name": "A"})
    check(r.status_code == 201, "create section")
    section_id = r.json()["id"]

    # 6. Add Subject & Teacher
    r = req("POST", "/subjects", token=sa_token, json={"school_id": school_id, "name": "Maths", "weekly_hours": 3})
    check(r.status_code == 201, "create subject")
    subject_id = r.json()["id"]

    t_email = f"valtest.teacher.{suffix}@example.com"
    r = req("POST", "/teachers", token=sa_token, json={
        "school_id": school_id, "name": "Teacher Math", "email": t_email, "password": "pass1234",
        "department": "Math", "max_weekly_hours": 20, "subject_ids": [subject_id]
    })
    check(r.status_code == 201, "create teacher")
    teacher_id = r.json()["id"]

    # 7. Add Subject Assignment
    r = req("POST", "/assignments", token=sa_token, json={
        "school_id": school_id,
        "section_id": section_id,
        "subject_id": subject_id,
        "teacher_id": teacher_id
    })
    check(r.status_code == 201, "create subject assignment")

    # 8. Check validation again (should be ready now)
    r = req("GET", f"/validation/school/{school_id}", token=sa_token)
    check(r.status_code == 200, "get validation report after configuration")
    data = r.json()
    check(data["readiness_score"] == 100, "readiness score is 100% after configuring assignment")
    check(len(data["errors"]) == 0, "no errors in validation list")

    # 9. Test version saving
    r = req("POST", "/timetables/versions/save-draft", token=sa_token, json={"school_id": school_id, "name": "Draft 1.0"})
    check(r.status_code == 200, "save draft version of current timetable")
    version_id = r.json()["id"]

    # 10. List versions
    r = req("GET", f"/timetables/versions?school_id={school_id}", token=sa_token)
    check(r.status_code == 200, "list versions for school")
    versions = r.json()
    check(len(versions) == 1, "versions list has 1 saved version")
    check(versions[0]["name"] == "Draft 1.0", "version name matches 'Draft 1.0'")

    # 11. Create a dummy slot in active timetable
    r = req("GET", f"/timetables?section_id={section_id}", token=sa_token)
    check(r.status_code == 200, "list active timetable slots (should be empty initially)")
    check(r.json()["total"] == 0, "active slots total is 0")

    # Generate timetable using OR-Tools (should succeed since validation has 0 errors)
    r = req("POST", "/timetables/generate", token=sa_token, json={"school_id": school_id, "time_limit_seconds": 10})
    check(r.status_code == 200, "generate master timetable successfully")

    # Now compare active vs draft (active should have Maths, draft is empty)
    r = req("POST", f"/timetables/versions/{version_id}/compare", token=sa_token)
    check(r.status_code == 200, "compare draft version against active")
    comp = r.json()
    check(len(comp["differences"]) > 0, "comparison returns slot differences")

    # Publish draft (should restore active to empty as saved in draft)
    r = req("POST", f"/timetables/versions/{version_id}/publish", token=sa_token)
    check(r.status_code == 200, "publish version (rollback to draft)")

    # Active should be empty again
    r = req("GET", f"/timetables?section_id={section_id}", token=sa_token)
    check(r.status_code == 200, "list active timetable slots after rollback")
    check(r.json()["total"] == 0, "active slots successfully reverted to 0")

    print("\nALL VALIDATION AND VERSIONING CHECKS PASSED SUCCESSFULLY!\n")

if __name__ == "__main__":
    main()
