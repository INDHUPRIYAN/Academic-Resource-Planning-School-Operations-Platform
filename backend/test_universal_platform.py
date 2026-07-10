import sys
import random
import requests
import json

BASE = "http://localhost:8000"

def req(method, path, token=None, **kw):
    headers = kw.pop("headers", {})
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return requests.request(method, f"{BASE}{path}", headers=headers, **kw)

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
    # Create super admin
    sa_email = f"univ.sa.{suffix}@example.com"
    sa = models.User(
        name="Universal SuperAdmin",
        email=sa_email,
        hashed_password=hash_password("pass1234"),
        role=models.RoleEnum.super_admin
    )
    db.add(sa)
    db.commit()
    db.close()

    # Login
    r = req("POST", "/auth/login", json={"email": sa_email, "password": "pass1234"})
    check(r.status_code == 200, "super_admin login")
    sa_token = r.json()["access_token"]

    # 1. Create a School
    r = req("POST", "/schools", token=sa_token, json={
        "name": f"Universal School {suffix}",
        "periods_per_day": 8,
        "working_days": 5
    })
    check(r.status_code == 201, "create school")
    school_id = r.json()["id"]

    # 2. Write Config: manual teacher assignment mode, resources enabled, pet end-of-day Timing enabled
    config_data = {
        "school_type": "CBSE",
        "academic_structure": {"grades": [f"Grade 6-{suffix}"]},
        "sections_per_grade": {},
        "mediums": {"enabled": False, "list": []},
        "teacher_assignment_method": "manual",  # <-- Explicit Manual mode
        "teacher_eligibility": {"enabled": False, "groups": []},
        "subject_configuration": {"hours_defined_at": "per_class"},
        "activities": {"enabled": False, "list": []},
        "resources": {"enabled": True},
        "substitution_policy": "automatic",
        "scheduling_policies": {
            "max_consecutive_periods": 3,
            "max_daily_periods": 8,
            "double_periods_allowed": False,
            "science_practical_consecutive": False,
            "pet_last_periods": True  # <-- PET sports must be in last 2 periods of the day
        }
    }

    r = req("PUT", f"/schools/{school_id}/config", token=sa_token, json={"config": json.dumps(config_data)})
    check(r.status_code == 200, "set school configuration to manual assignment & PET constraints")

    # 3. Create Class and Section
    r = req("POST", "/classes", token=sa_token, json={"name": f"Grade 6-{suffix}", "school_id": school_id})
    check(r.status_code == 201, "create grade class")
    class_id = r.json()["id"]

    r = req("POST", "/sections", token=sa_token, json={"name": "A", "class_id": class_id})
    check(r.status_code == 201, "create section A")
    section_id = r.json()["id"]

    # 4. Create Subjects
    # Maths has 5 hours. PET (Sports) has 2 hours.
    r = req("POST", "/subjects", token=sa_token, json={"name": f"Maths-{suffix}", "weekly_hours": 5, "school_id": school_id})
    check(r.status_code == 201, "create Maths subject")
    maths_id = r.json()["id"]

    r = req("POST", "/subjects", token=sa_token, json={"name": f"PET-{suffix}", "weekly_hours": 2, "school_id": school_id})
    check(r.status_code == 201, "create PET subject")
    pet_id = r.json()["id"]

    # 5. Create Teachers
    r = req("POST", "/teachers", token=sa_token, json={
        "school_id": school_id, "name": f"Maths Teacher-{suffix}", "email": f"maths.{suffix}@school.com",
        "password": "Password@123", "department": "Math", "max_weekly_hours": 30, "subject_ids": [maths_id]
    })
    check(r.status_code == 201, "create Maths teacher")
    maths_teacher_id = r.json()["id"]

    r = req("POST", "/teachers", token=sa_token, json={
        "school_id": school_id, "name": f"Sports Instructor-{suffix}", "email": f"sports.{suffix}@school.com",
        "password": "Password@123", "department": "Sports", "max_weekly_hours": 30, "subject_ids": [pet_id]
    })
    check(r.status_code == 201, "create PET teacher")
    pet_teacher_id = r.json()["id"]

    # 6. Create Explicit Assignments
    # Map Section -> Subject -> Teacher
    r = req("POST", "/assignments", token=sa_token, json={
        "school_id": school_id, "section_id": section_id, "subject_id": maths_id, "teacher_id": maths_teacher_id
    })
    check(r.status_code == 201, "manually assign Maths teacher to Grade 6A Maths")

    r = req("POST", "/assignments", token=sa_token, json={
        "school_id": school_id, "section_id": section_id, "subject_id": pet_id, "teacher_id": pet_teacher_id
    })
    check(r.status_code == 201, "manually assign PET teacher to Grade 6A PET")

    # 7. Generate Master Timetable
    r = req("POST", "/timetables/generate", token=sa_token, json={"school_id": school_id, "time_limit_seconds": 15})
    check(r.status_code == 200, "generate timetable under manual config")
    
    slots_count = r.json()["slots_created"]
    check(slots_count == 7, f"verify 7 slots created (5 Maths + 2 PET)")

    # 8. Query generated timetable slots to verify constraints
    r = req("GET", f"/timetables?section_id={section_id}&limit=100", token=sa_token)
    slots = r.json()["items"]
    
    # Check that Maths teacher taught Maths and PET teacher taught PET (manual assignment validation)
    for s in slots:
        if s["subject_id"] == maths_id:
            check(s["teacher_id"] == maths_teacher_id, "verify Maths slot uses manually assigned Maths teacher")
        elif s["subject_id"] == pet_id:
            check(s["teacher_id"] == pet_teacher_id, "verify PET slot uses manually assigned PET teacher")
            # Verify PET sports timing policy is respected: must be in last 2 periods of the day (periods 7, 8)
            check(s["period"] in (7, 8), f"verify PET slot timing constraint: period={s['period']}")

    print("\nALL UNIVERSAL TIMETABLE CONFIG & EXPLICIT ASSIGNMENT TESTS PASSED SUCCESSFULLY!")

if __name__ == "__main__":
    main()
