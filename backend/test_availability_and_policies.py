import sys
import random
import requests

BASE = "http://localhost:8005"

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
    r = req("POST", "/schools", token=sa_token, json={"name": f"Policy Test School {suffix}", "periods_per_day": 8, "working_days": 5})
    check(r.status_code == 201, "create school")
    school_id = r.json()["id"]

    # 4. Add Class & Section
    r = req("POST", "/classes", token=sa_token, json={"school_id": school_id, "name": "Grade 10"})
    check(r.status_code == 201, "create class")
    class_id = r.json()["id"]

    r = req("POST", "/sections", token=sa_token, json={"class_id": class_id, "name": "A"})
    check(r.status_code == 201, "create section")
    section_id = r.json()["id"]

    # 5. Add Subject & Teacher
    # Maths (weekly_hours = 3)
    r = req("POST", "/subjects", token=sa_token, json={"school_id": school_id, "name": "Maths", "weekly_hours": 3})
    check(r.status_code == 201, "create Maths subject")
    maths_id = r.json()["id"]

    t_email = f"teacher.math.{suffix}@example.com"
    r = req("POST", "/teachers", token=sa_token, json={
        "school_id": school_id, "name": "Teacher Math", "email": t_email, "password": "pass1234",
        "department": "Math", "max_weekly_hours": 20, "subject_ids": [maths_id]
    })
    check(r.status_code == 201, "create Maths teacher")
    teacher_id = r.json()["id"]

    # 6. Subject Assignment
    r = req("POST", "/assignments", token=sa_token, json={
        "school_id": school_id,
        "section_id": section_id,
        "subject_id": maths_id,
        "teacher_id": teacher_id
    })
    check(r.status_code == 201, "create assignment")

    # 7. Test Teacher Availability CRUD
    # Get initial availability (should be empty list)
    r = req("GET", f"/teachers/{teacher_id}/availability", token=sa_token)
    check(r.status_code == 200, "GET initial availability empty list")
    check(len(r.json()) == 0, "length of availability list is 0")

    # Bulk update: set Monday period 1 as blocked
    payload = [
        {"day_of_week": 0, "period": 1, "is_available": False},
        {"day_of_week": 0, "period": 2, "is_available": True}
    ]
    r = req("PUT", f"/teachers/{teacher_id}/availability", token=sa_token, json=payload)
    check(r.status_code == 200, "PUT teacher availability")
    check(len(r.json()) == 2, "PUT response has 2 items")

    # Verify get availability
    r = req("GET", f"/teachers/{teacher_id}/availability", token=sa_token)
    check(r.status_code == 200, "GET availability")
    data = r.json()
    blocked_slot = next(x for x in data if x["day_of_week"] == 0 and x["period"] == 1)
    check(blocked_slot["is_available"] == False, "Monday period 1 is blocked")

    # 8. Test Teacher Preference CRUD
    # Get preferences (empty list)
    r = req("GET", f"/teachers/{teacher_id}/preferences", token=sa_token)
    check(r.status_code == 200, "GET initial preferences empty")
    check(len(r.json()) == 0, "preferences empty")

    # Add preference: max_daily = 1
    r = req("POST", f"/teachers/{teacher_id}/preferences", token=sa_token, json={
        "preference_type": "max_daily",
        "value": 1
    })
    check(r.status_code == 201, "POST teacher preference")
    pref_id = r.json()["id"]

    # Verify list
    r = req("GET", f"/teachers/{teacher_id}/preferences", token=sa_token)
    check(r.status_code == 200, "GET preferences list")
    check(len(r.json()) == 1, "preferences list has 1 item")

    # 9. Test Timetable Generation with Availability and Preferences
    # Generate Timetable
    r = req("POST", "/timetables/generate", token=sa_token, json={"school_id": school_id})
    check(r.status_code == 200, "generate timetable with policies & availability")

    # Fetch generated timetable for section
    r = req("GET", f"/timetables/section/{section_id}", token=sa_token)
    check(r.status_code == 200, "GET section timetable")
    slots = r.json()["slots"]
    maths_slots = [s for s in slots if s["subject_id"] == maths_id]
    check(len(maths_slots) == 3, "scheduled 3 hours of Maths")

    # Verify Monday Period 1 has no Maths scheduled (as the teacher was blocked)
    mon_p1 = next((s for s in maths_slots if s["day_of_week"] == 0 and s["period"] == 1), None)
    check(mon_p1 is None, "Maths NOT scheduled on Monday period 1 (availability respected)")

    # Verify max_daily = 1 preference is respected (since Maths hours is 3, they must be scheduled on 3 different days, max 1 per day)
    scheduled_days = [s["day_of_week"] for s in maths_slots]
    check(len(set(scheduled_days)) == 3, "Maths scheduled on 3 different days due to max_daily=1 limit preference")

    # Delete preference
    r = req("DELETE", f"/teachers/{teacher_id}/preferences/{pref_id}", token=sa_token)
    check(r.status_code == 204, "DELETE teacher preference")

    print("\nALL POLICY & AVAILABILITY TESTS PASSED SUCCESSFULLY!")

if __name__ == "__main__":
    main()
