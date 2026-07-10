"""
End-to-end test for Phase 5 (Swap Management), hitting a live uvicorn
instance over HTTP exactly like the frontend would. Same approach as
Phase 4's test_leaves_ui.py.

Timetable rows are created directly via the DB session (not through
/timetables/generate) so the test has full, deterministic control over
which teacher sits at which (day_of_week, period) — this is what lets us
reliably provoke the 409 double-booking conflict case.

Run: start the server first (see README), then:
    python test_swaps_ui.py
"""
import sys
import datetime
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
    sa_email = f"swaptest.superadmin.{suffix}@example.com"
    sa = models.User(name="SwapTest SuperAdmin", email=sa_email,
                      hashed_password=hash_password("pass1234"), role=models.RoleEnum.super_admin)
    db.add(sa)
    db.commit()
    db.close()

    r = req("POST", "/auth/login", json={"email": sa_email, "password": "pass1234"})
    check(r.status_code == 200, "super_admin login")
    sa_token = r.json()["access_token"]

    # --- school, 2 classes/sections, 1 subject ---
    r = req("POST", "/schools", token=sa_token, json={"name": f"Swap Test School {suffix}", "periods_per_day": 8, "working_days": 5})
    check(r.status_code == 201, "create school")
    school_id = r.json()["id"]

    r = req("POST", "/classes", token=sa_token, json={"name": "Grade 6", "school_id": school_id})
    class_id = r.json()["id"]
    r = req("POST", "/sections", token=sa_token, json={"name": "A", "class_id": class_id})
    section_a = r.json()["id"]
    r = req("POST", "/sections", token=sa_token, json={"name": "B", "class_id": class_id})
    section_b = r.json()["id"]

    r = req("POST", "/subjects", token=sa_token, json={"name": "Science", "weekly_hours": 4, "school_id": school_id})
    subject_id = r.json()["id"]

    def make_teacher(email):
        r = req("POST", "/teachers", token=sa_token, json={
            "name": email.split("@")[0], "email": email, "password": "pass1234",
            "department": "Science", "max_weekly_hours": 30, "school_id": school_id, "subject_ids": [subject_id],
        })
        check(r.status_code == 201, f"create teacher {email}")
        return r.json()["id"]

    t1_id = make_teacher(f"swt1.{suffix}@example.com")
    t2_id = make_teacher(f"swt2.{suffix}@example.com")
    t3_id = make_teacher(f"swt3.{suffix}@example.com")

    r = req("POST", "/auth/login", json={"email": f"swt1.{suffix}@example.com", "password": "pass1234"})
    t1_token = r.json()["access_token"]
    r = req("POST", "/auth/login", json={"email": f"swt2.{suffix}@example.com", "password": "pass1234"})
    t2_token = r.json()["access_token"]
    r = req("POST", "/auth/login", json={"email": f"swt3.{suffix}@example.com", "password": "pass1234"})
    t3_token = r.json()["access_token"]

    # --- directly create deterministic master-timetable rows (Monday = day_of_week 0) ---
    from app.database import SessionLocal
    from app import models as m
    db = SessionLocal()

    def add_slot(section_id, day, period, teacher_id):
        row = m.Timetable(school_id=school_id, section_id=section_id, subject_id=subject_id,
                           teacher_id=teacher_id, day_of_week=day, period=period)
        db.add(row)
        db.commit()
        db.refresh(row)
        return row.id

    slot1 = add_slot(section_a, 0, 1, t1_id)   # section A, Mon P1, t1
    slot2 = add_slot(section_a, 0, 2, t2_id)   # section A, Mon P2, t2
    slot_conflict = add_slot(section_b, 0, 2, t1_id)  # section B, Mon P2, t1 (already busy at P2!)
    slot4 = add_slot(section_a, 0, 4, t2_id)   # section A, Mon P4, t2 (no conflict with t1 at P4)
    db.close()

    # figure out a real future Monday
    today = datetime.date.today()
    days_ahead = (0 - today.weekday()) % 7
    days_ahead = days_ahead if days_ahead > 0 else 7
    monday = today + datetime.timedelta(days=days_ahead)
    monday2 = monday + datetime.timedelta(days=7)

    # --- weekday validation: date must match slots' day_of_week ---
    r = req("POST", "/swaps", token=t1_token, json={
        "timetable_id_a": slot1, "timetable_id_b": slot2, "date": str(today + datetime.timedelta(days=1)),
    })
    check(r.status_code == 400, "swap rejected when date's weekday != slot day_of_week")

    # --- permission: t3 (not involved in slot1 or slot2) cannot request this swap ---
    r = req("POST", "/swaps", token=t3_token, json={
        "timetable_id_a": slot1, "timetable_id_b": slot2, "date": str(monday),
    })
    check(r.status_code == 403, "teacher not involved in either slot cannot request the swap")

    # --- t1 requests a swap that WILL conflict on approval (slot1 <-> slot2; t1 already busy at P2) ---
    r = req("POST", "/swaps", token=t1_token, json={
        "timetable_id_a": slot1, "timetable_id_b": slot2, "date": str(monday), "reason": "Prefer P2 that day",
    })
    check(r.status_code == 201, f"t1 requests swap slot1<->slot2 ({r.text if r.status_code != 201 else ''})")
    conflict_swap_id = r.json()["id"]
    check(r.json()["status"] == "pending", "swap starts pending")

    r = req("POST", f"/swaps/{conflict_swap_id}/approve", token=t1_token, json={})
    check(r.status_code == 403, "teacher cannot approve a swap")

    r = req("GET", "/swaps", token=sa_token, params={"status": "pending"})
    check(r.status_code == 200 and any(s["id"] == conflict_swap_id for s in r.json()["items"]), "admin sees pending swap")

    r = req("POST", f"/swaps/{conflict_swap_id}/approve", token=sa_token, json={})
    check(r.status_code == 409, f"approval blocked: t1 would double-book at P2 ({r.text})")

    # admin rejects the conflicting one instead
    r = req("POST", f"/swaps/{conflict_swap_id}/reject", token=sa_token, json={"note": "Would double-book you"})
    check(r.status_code == 200 and r.json()["status"] == "rejected", "reject the conflicting swap")

    r = req("GET", "/notifications", token=t1_token)
    check(r.status_code == 200 and any("rejected" in n["message"] for n in r.json()["items"]), "t1 notified of rejection")

    # --- t2 requests a CLEAN swap: slot1 (t1, P1) <-> slot4 (t2, P4), no conflicts ---
    r = req("POST", "/swaps", token=t2_token, json={
        "timetable_id_a": slot1, "timetable_id_b": slot4, "date": str(monday), "reason": "Swap our periods",
    })
    check(r.status_code == 201, f"t2 requests clean swap slot1<->slot4 ({r.text if r.status_code != 201 else ''})")
    clean_swap_id = r.json()["id"]

    r = req("POST", f"/swaps/{clean_swap_id}/approve", token=sa_token, json={"note": "Looks fine"})
    check(r.status_code == 200, f"admin approves clean swap ({r.text if r.status_code != 200 else ''})")
    check(r.json()["status"] == "approved", "swap now approved")

    # both t1 and t2 notified
    r = req("GET", "/notifications", token=t1_token)
    check(r.status_code == 200 and any("swap" in n["message"].lower() for n in r.json()["items"]), "t1 notified of swap")
    r = req("GET", "/notifications", token=t2_token)
    check(r.status_code == 200 and any("swap" in n["message"].lower() for n in r.json()["items"]), "t2 notified of swap")

    # --- re-approving / re-rejecting an already-decided swap should fail ---
    r = req("POST", f"/swaps/{clean_swap_id}/approve", token=sa_token, json={})
    check(r.status_code == 400, "cannot re-approve an already-approved swap")

    # --- Layer 2: effective schedule for that Monday reflects the swap ---
    r = req("GET", "/substitutions/schedule", token=sa_token, params={"date": str(monday), "section_id": section_a})
    check(r.status_code == 200, "get effective schedule for swap date")
    eff = {s["period"]: s for s in r.json()}
    check(eff[1]["is_swapped"] is True and eff[1]["teacher_id"] == t2_id, "P1 now shows t2 (swapped in from P4)")
    check(eff[4]["is_swapped"] is True and eff[4]["teacher_id"] == t1_id, "P4 now shows t1 (swapped in from P1)")

    # --- Layer 1: master timetable itself is untouched ---
    r = req("GET", f"/timetables/teacher/{t1_id}", token=sa_token)
    check(r.status_code == 200, "get t1 master timetable")
    t1_master_periods = sorted(s["period"] for s in r.json()["slots"] if s["day_of_week"] == 0)
    check(t1_master_periods == [1, 2], "t1's master timetable unchanged (still P1 + P2, Layer 2 overlay only)")

    # --- a swap on a DIFFERENT date (same weekday) does not affect this one ---
    r = req("GET", "/substitutions/schedule", token=sa_token, params={"date": str(monday2), "section_id": section_a})
    check(r.status_code == 200, "get effective schedule for a different Monday")
    eff2 = {s["period"]: s for s in r.json()}
    check(eff2[1]["is_swapped"] is False and eff2[1]["teacher_id"] == t1_id, "different date: P1 still shows t1 unswapped")

    # --- cancel flow: t3 requests a pending swap involving their own slots, then cancels it ---
    db = SessionLocal()
    row = m.Timetable(school_id=school_id, section_id=section_b, subject_id=subject_id, teacher_id=t3_id, day_of_week=0, period=5)
    db.add(row)
    db.commit()
    db.refresh(row)
    slot5 = row.id
    row2 = m.Timetable(school_id=school_id, section_id=section_b, subject_id=subject_id, teacher_id=t3_id, day_of_week=0, period=6)
    db.add(row2)
    db.commit()
    db.refresh(row2)
    slot6 = row2.id
    db.close()

    r = req("POST", "/swaps", token=t3_token, json={"timetable_id_a": slot5, "timetable_id_b": slot6, "date": str(monday)})
    check(r.status_code == 201, "t3 requests own swap")
    own_swap_id = r.json()["id"]

    r = req("DELETE", f"/swaps/{own_swap_id}", token=t2_token)
    check(r.status_code == 403, "another teacher cannot cancel someone else's swap request")

    r = req("DELETE", f"/swaps/{own_swap_id}", token=t3_token)
    check(r.status_code == 204, "t3 cancels their own pending swap")

    r = req("GET", f"/swaps/{own_swap_id}", token=sa_token)
    check(r.status_code == 404, "cancelled swap is gone")

    print("\nALL PHASE 5 TESTS PASSED")


if __name__ == "__main__":
    main()
