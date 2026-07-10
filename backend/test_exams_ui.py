"""
End-to-end test for Phase 6 (Exam Module), hitting a live uvicorn instance
over HTTP exactly like the frontend would. Same approach as
test_leaves_ui.py / test_swaps_ui.py.

Timetable rows are seeded directly via the DB session (not through
/timetables/generate) so /exams/generate has deterministic (section,
subject) pairs to work from.

⚠️ NOT YET RUN — written in a no-network sandbox this session (see
README "Exam Module (Phase 6)" and the handoff prompt for details).
Syntax-checked with py_compile only. Run this against a live server
before treating Phase 6 as verified.

Run: start the server first (see README), then:
    python test_exams_ui.py
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
    import datetime as dt

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    sa_email = f"examtest.superadmin.{suffix}@example.com"
    sa = models.User(name="ExamTest SuperAdmin", email=sa_email,
                      hashed_password=hash_password("pass1234"), role=models.RoleEnum.super_admin)
    db.add(sa)
    db.commit()
    db.close()

    r = req("POST", "/auth/login", json={"email": sa_email, "password": "pass1234"})
    check(r.status_code == 200, "super_admin login")
    sa_token = r.json()["access_token"]

    # --- school, class, 2 sections, 2 subjects, a resource ---
    r = req("POST", "/schools", token=sa_token, json={"name": f"Exam Test School {suffix}", "periods_per_day": 8, "working_days": 5})
    check(r.status_code == 201, "create school")
    school_id = r.json()["id"]

    r = req("POST", "/classes", token=sa_token, json={"name": "Grade 8", "school_id": school_id})
    class_id = r.json()["id"]
    r = req("POST", "/sections", token=sa_token, json={"name": "A", "class_id": class_id})
    section_a = r.json()["id"]
    r = req("POST", "/sections", token=sa_token, json={"name": "B", "class_id": class_id})
    section_b = r.json()["id"]

    r = req("POST", "/subjects", token=sa_token, json={"name": "Maths", "weekly_hours": 5, "school_id": school_id})
    subj_math = r.json()["id"]
    r = req("POST", "/subjects", token=sa_token, json={"name": "English", "weekly_hours": 5, "school_id": school_id})
    subj_eng = r.json()["id"]

    r = req("POST", "/resources", token=sa_token, json={"name": "Hall 1", "type": "hall", "capacity": 100, "school_id": school_id})
    hall_id = r.json()["id"]

    def make_teacher(email, subject_ids):
        r = req("POST", "/teachers", token=sa_token, json={
            "name": email.split("@")[0], "email": email, "password": "pass1234",
            "department": "General", "max_weekly_hours": 30, "school_id": school_id, "subject_ids": subject_ids,
        })
        check(r.status_code == 201, f"create teacher {email}")
        return r.json()["id"]

    t1_id = make_teacher(f"extt1.{suffix}@example.com", [subj_math])
    t2_id = make_teacher(f"extt2.{suffix}@example.com", [subj_eng])

    r = req("POST", "/auth/login", json={"email": f"extt1.{suffix}@example.com", "password": "pass1234"})
    t1_token = r.json()["access_token"]

    # --- seed master-timetable rows directly so section A/B are "taught"
    # Maths and English (gives /exams/generate real (section, subject) pairs) ---
    db = SessionLocal()
    for sec_id in (section_a, section_b):
        db.add(models.Timetable(school_id=school_id, section_id=sec_id, subject_id=subj_math,
                                 teacher_id=t1_id, day_of_week=0, period=1))
        db.add(models.Timetable(school_id=school_id, section_id=sec_id, subject_id=subj_eng,
                                 teacher_id=t2_id, day_of_week=0, period=2))
    db.commit()
    db.close()

    # --- manual exam scheduling ---
    exam_date = "2026-08-10"  # a Monday
    r = req("POST", "/exams", token=t1_token, json={
        "subject_id": subj_math, "section_id": section_a, "date": exam_date,
        "start_time": "09:00:00", "end_time": "10:30:00",
    })
    check(r.status_code == 403, "teacher (non-admin) cannot create an exam")

    r = req("POST", "/exams", token=sa_token, json={
        "subject_id": subj_math, "section_id": section_a, "resource_id": hall_id, "invigilator_id": t2_id,
        "date": exam_date, "start_time": "09:00:00", "end_time": "10:30:00",
    })
    check(r.status_code == 201, "admin creates a manual exam")
    exam1_id = r.json()["id"]
    check(r.json()["section_name"].endswith("A"), "exam response includes denormalized section_name")

    # overlapping same section -> 409
    r = req("POST", "/exams", token=sa_token, json={
        "subject_id": subj_eng, "section_id": section_a, "date": exam_date,
        "start_time": "09:30:00", "end_time": "11:00:00",
    })
    check(r.status_code == 409, "overlapping exam for the same section is blocked (409)")

    # overlapping room -> 409
    r = req("POST", "/exams", token=sa_token, json={
        "subject_id": subj_eng, "section_id": section_b, "resource_id": hall_id,
        "date": exam_date, "start_time": "09:15:00", "end_time": "10:00:00",
    })
    check(r.status_code == 409, "overlapping exam for the same room is blocked (409)")

    # overlapping invigilator -> 409
    r = req("POST", "/exams", token=sa_token, json={
        "subject_id": subj_eng, "section_id": section_b, "invigilator_id": t2_id,
        "date": exam_date, "start_time": "09:15:00", "end_time": "10:00:00",
    })
    check(r.status_code == 409, "overlapping exam for the same invigilator is blocked (409)")

    # non-overlapping (different section, different time) -> 201
    r = req("POST", "/exams", token=sa_token, json={
        "subject_id": subj_eng, "section_id": section_b, "date": exam_date,
        "start_time": "11:00:00", "end_time": "12:00:00",
    })
    check(r.status_code == 201, "non-overlapping exam succeeds (201)")
    exam2_id = r.json()["id"]

    # update: move exam2 to overlap exam1's section/time -> should still be fine (different section)
    r = req("PUT", f"/exams/{exam2_id}", token=sa_token, json={"start_time": "09:00:00", "end_time": "10:30:00"})
    check(r.status_code == 200, "reschedule exam2 to same time, different section (no conflict) succeeds")

    # update exam2 into an actual conflict -> 409
    r = req("PUT", f"/exams/{exam2_id}", token=sa_token, json={"section_id": section_a})
    check(r.status_code == 409, "rescheduling into a conflict is blocked (409)")

    # list / get
    r = req("GET", f"/exams?section_id={section_a}", token=sa_token)
    check(r.status_code == 200 and r.json()["total"] >= 1, "list exams filtered by section")
    r = req("GET", f"/exams/{exam1_id}", token=sa_token)
    check(r.status_code == 200, "get single exam")

    # delete
    r = req("DELETE", f"/exams/{exam2_id}", token=sa_token)
    check(r.status_code == 204, "delete exam")
    r = req("GET", f"/exams/{exam2_id}", token=sa_token)
    check(r.status_code == 404, "deleted exam is gone")

    # --- generator ---
    r = req("POST", "/exams/generate", token=sa_token, json={
        "school_id": school_id,
        "section_ids": [section_a, section_b],
        "start_date": "2026-08-17",  # a Monday, clear of the manual exam above
        "end_date": "2026-08-21",    # through Friday
        "exams_per_day": 2,
        "daily_start_time": "09:00:00",
        "duration_minutes": 60,
        "gap_minutes": 15,
    })
    check(r.status_code == 200, "generate exams")
    gen = r.json()
    # 2 sections x 2 subjects (Maths, English) = 4 pairs; should all be
    # placeable well within a 5-day x 2-slot/day window.
    check(gen["exams_created"] == 4, f"generator created all 4 (section,subject) pairs (got {gen['exams_created']})")
    check(len(gen["unscheduled"]) == 0, "nothing left unscheduled")

    # sanity: no generated exam falls on a weekend
    r = req("GET", "/exams", token=sa_token, params={"start_date": "2026-08-17", "end_date": "2026-08-21", "limit": 50})
    check(r.status_code == 200, "list generated exams")
    import datetime as dt2
    for item in r.json()["items"]:
        d = dt2.date.fromisoformat(item["date"])
        check(d.weekday() < 5, f"generated exam on {item['date']} falls on a weekday")

    # generating again over the same range with the same pairs should now
    # find those exact (date,time) x section slots taken and either skip
    # them (already scheduled) or push into new slots without 409ing.
    r = req("POST", "/exams/generate", token=sa_token, json={
        "school_id": school_id, "section_ids": [section_a, section_b],
        "start_date": "2026-08-17", "end_date": "2026-08-21",
        "exams_per_day": 2, "daily_start_time": "09:00:00", "duration_minutes": 60, "gap_minutes": 15,
    })
    check(r.status_code == 200, "re-running generator over the same range doesn't error")

    print("\nAll Phase 6 (Exam Module) checks passed.")


if __name__ == "__main__":
    main()
