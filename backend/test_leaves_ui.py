"""
End-to-end test for Phase 4 (Leave Management + Auto Substitution +
Notifications), hitting a live uvicorn instance over HTTP exactly like the
frontend would. Same approach as Phases 1-3 (test_timetable_ui.py, not
included in the zip).

Run: start the server first (see README), then:
    python test_leaves_ui.py
"""
import sys
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
    # --- bootstrap super admin (idempotent-ish: use unique emails per run) ---
    import random
    suffix = random.randint(10000, 99999)

    # login as existing super admin if present, else create one directly via DB
    from app.database import SessionLocal, Base, engine
    from app import models
    from app.auth import hash_password
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    sa_email = f"leavetest.superadmin.{suffix}@example.com"
    sa = models.User(name="LeaveTest SuperAdmin", email=sa_email,
                      hashed_password=hash_password("pass1234"), role=models.RoleEnum.super_admin)
    db.add(sa)
    db.commit()
    db.close()

    r = req("POST", "/auth/login", json={"email": sa_email, "password": "pass1234"})
    check(r.status_code == 200, "super_admin login")
    sa_token = r.json()["access_token"]

    # --- school ---
    r = req("POST", "/schools", token=sa_token, json={"name": f"Leave Test School {suffix}", "periods_per_day": 6, "working_days": 5})
    check(r.status_code == 201, "create school")
    school_id = r.json()["id"]

    # --- class + 1 section ---
    r = req("POST", "/classes", token=sa_token, json={"name": "Grade 5", "school_id": school_id})
    check(r.status_code == 201, "create class")
    class_id = r.json()["id"]
    r = req("POST", "/sections", token=sa_token, json={"name": "A", "class_id": class_id})
    check(r.status_code == 201, "create section")
    section_id = r.json()["id"]

    # --- subject ---
    r = req("POST", "/subjects", token=sa_token, json={"name": "Maths", "weekly_hours": 1, "school_id": school_id})
    check(r.status_code == 201, "create subject")
    subject_id = r.json()["id"]

    # --- 3 teachers: t1 (goes on leave, same-subject), t2 (same subject, free -> should get picked), t3 (different subject) ---
    def make_teacher(email, dept, subject_ids):
        r = req("POST", "/teachers", token=sa_token, json={
            "name": email.split("@")[0], "email": email, "password": "pass1234",
            "department": dept, "max_weekly_hours": 30, "school_id": school_id, "subject_ids": subject_ids,
        })
        check(r.status_code == 201, f"create teacher {email}")
        return r.json()["id"]

    t1_id = make_teacher(f"t1.{suffix}@example.com", "Science", [subject_id])
    t2_id = make_teacher(f"t2.{suffix}@example.com", "Science", [subject_id])
    t3_id = make_teacher(f"t3.{suffix}@example.com", "Arts", [])

    # --- login as t1 (the teacher who will apply for leave) ---
    r = req("POST", "/auth/login", json={"email": f"t1.{suffix}@example.com", "password": "pass1234"})
    check(r.status_code == 200, "teacher t1 login")
    t1_token = r.json()["access_token"]

    r = req("POST", "/auth/login", json={"email": f"t2.{suffix}@example.com", "password": "pass1234"})
    t2_token = r.json()["access_token"]

    # --- generate a timetable so t1 has real master-timetable slots ---
    r = req("POST", "/timetables/generate", token=sa_token, json={"school_id": school_id, "time_limit_seconds": 15})
    check(r.status_code == 200, f"generate timetable ({r.text if r.status_code != 200 else 'ok'})")

    # The solver freely picks any qualified teacher for the subject's hours,
    # so it may have put all 4 weekly hours on t1, t2, or split between them.
    # Pick whichever of t1/t2 actually got slots as the one who'll take leave.
    r = req("GET", f"/timetables/teacher/{t1_id}", token=sa_token)
    check(r.status_code == 200, "get t1 timetable grid")
    t1_slots = r.json()["slots"]
    if not t1_slots:
        r = req("GET", f"/timetables/teacher/{t2_id}", token=sa_token)
        check(r.status_code == 200, "get t2 timetable grid")
        t2_slots_check = r.json()["slots"]
        check(len(t2_slots_check) > 0, "at least one of t1/t2 has scheduled slots")
        print("  -> swapping roles: t2 will take leave, t1 becomes the same-subject substitute")
        t1_id, t2_id = t2_id, t1_id
        t1_token, t2_token = t2_token, t1_token
        t1_slots = t2_slots_check
    check(len(t1_slots) > 0, "leave-taking teacher has at least one scheduled slot")
    target_day = t1_slots[0]["day_of_week"]

    # figure out a real calendar date that falls on target_day's weekday
    import datetime
    today = datetime.date.today()
    days_ahead = (target_day - today.weekday()) % 7
    days_ahead = days_ahead if days_ahead > 0 else 7  # ensure it's in the future, avoids "past date" ambiguity
    leave_date = today + datetime.timedelta(days=days_ahead)

    # --- t1 applies for leave (self-service, teacher role) ---
    r = req("POST", "/leaves", token=t1_token, json={"date": str(leave_date), "reason": "Medical appointment"})
    check(r.status_code == 201, f"t1 applies for leave ({r.text if r.status_code != 201 else ''})")
    leave = r.json()
    leave_id = leave["id"]
    check(leave["status"] == "pending", "leave starts pending")

    # teacher cannot approve their own leave
    r = req("POST", f"/leaves/{leave_id}/approve", token=t1_token, json={})
    check(r.status_code == 403, "teacher cannot approve leave (403)")

    # --- admin lists pending leaves, sees it ---
    r = req("GET", "/leaves", token=sa_token, params={"status": "pending"})
    check(r.status_code == 200 and any(l["id"] == leave_id for l in r.json()["items"]), "admin sees pending leave")

    # --- admin approves -> auto substitute engine runs ---
    r = req("POST", f"/leaves/{leave_id}/approve", token=sa_token, json={"note": "Approved, get well soon"})
    check(r.status_code == 200, f"admin approves leave ({r.text if r.status_code != 200 else ''})")
    result = r.json()
    check(result["leave"]["status"] == "approved", "leave now approved")
    check(result["substitutions_created"] == len(t1_slots), f"substitution created for every slot ({result['substitutions_created']}/{len(t1_slots)})")
    check(len(result["uncovered_slots"]) == 0, "no uncovered slots (t2/t3 available)")

    # --- verify t2 (same subject) got picked over t3 for at least one slot ---
    r = req("GET", "/substitutions", token=sa_token, params={"leave_id": leave_id})
    check(r.status_code == 200, "list substitutions for leave")
    subs = r.json()["items"]
    check(len(subs) == len(t1_slots), "substitution count matches slot count")
    same_subject_matches = [s for s in subs if s["method"] == "same_subject"]
    check(len(same_subject_matches) > 0, "at least one same-subject match")
    check(all(s["substitute_teacher_id"] == t2_id for s in same_subject_matches), "same-subject matches went to t2 (only same-subject candidate)")

    # --- t2 got a notification ---
    r = req("GET", "/notifications", token=t2_token)
    check(r.status_code == 200, "t2 fetch notifications")
    check(r.json()["unread_count"] >= 1, "t2 has at least 1 unread notification")
    notif_id = r.json()["items"][0]["id"]
    r = req("PATCH", f"/notifications/{notif_id}/read", token=t2_token)
    check(r.status_code == 200 and r.json()["is_read"] is True, "mark notification read")

    # --- t1 got an approval notification ---
    r = req("GET", "/notifications", token=t1_token)
    check(r.status_code == 200 and any("approved" in n["message"] for n in r.json()["items"]), "t1 notified of approval")

    # --- effective schedule (Layer 2) for that date shows the substitute, not t1 ---
    r = req("GET", "/substitutions/schedule", token=sa_token, params={"date": str(leave_date), "section_id": section_id})
    check(r.status_code == 200, "get effective schedule")
    eff = r.json()
    substituted = [s for s in eff if s["is_substituted"]]
    check(len(substituted) == len(t1_slots), f"effective schedule shows {len(t1_slots)} substituted slot(s)")
    check(all(s["teacher_id"] != t1_id for s in substituted), "t1 no longer appears as teacher on substituted slots")

    # --- master timetable itself is untouched (Layer 1 unchanged) ---
    r = req("GET", f"/timetables/teacher/{t1_id}", token=sa_token)
    check(r.status_code == 200 and len(r.json()["slots"]) == len(t1_slots), "master timetable for t1 unchanged (Layer 2 overlay only)")

    # --- double-decision guard: approving again should fail ---
    r = req("POST", f"/leaves/{leave_id}/approve", token=sa_token, json={})
    check(r.status_code == 400, "cannot re-approve an already-approved leave")

    # --- manual substitution flow: create + reassign + delete on a fresh leave/day for t3 (no other Arts teacher -> uncovered) ---
    days_ahead2 = ((target_day - today.weekday()) % 7) or 7
    days_ahead2 += 7  # a different date, still same weekday
    leave_date2 = today + datetime.timedelta(days=days_ahead2)
    # give t3 a slot by generating isn't guaranteed; instead directly test uncovered path via t1 second leave after making t2 also on leave that day
    r = req("POST", "/leaves", token=t1_token, json={"date": str(leave_date2), "reason": "Second leave"})
    check(r.status_code == 201, "t1 applies for a second leave (different date)")
    leave2_id = r.json()["id"]
    # also put t2 on approved leave that same day, so t1's slots become uncovered (only t3, different subject) unless t3 is free
    r = req("POST", "/leaves", token=sa_token, json={"teacher_id": t2_id, "date": str(leave_date2), "reason": "Also out"})
    check(r.status_code == 201, "admin submits leave for t2 on same date")
    leave3_id = r.json()["id"]
    r = req("POST", f"/leaves/{leave3_id}/approve", token=sa_token, json={})
    check(r.status_code == 200, "approve t2's leave (t2 now unavailable as substitute)")
    # and t3 too, so every other teacher at the school is out -> guaranteed uncovered
    r = req("POST", "/leaves", token=sa_token, json={"teacher_id": t3_id, "date": str(leave_date2), "reason": "Also out"})
    leave3b_id = r.json()["id"]
    r = req("POST", f"/leaves/{leave3b_id}/approve", token=sa_token, json={})
    check(r.status_code == 200, "approve t3's leave (no candidates left -> uncovered expected)")

    r = req("POST", f"/leaves/{leave2_id}/approve", token=sa_token, json={})
    check(r.status_code == 200, "approve t1's second leave")
    result2 = r.json()
    check(result2["substitutions_created"] + len(result2["uncovered_slots"]) == len(t1_slots), "all slots accounted for (substituted or uncovered)")
    check(len(result2["uncovered_slots"]) == len(t1_slots), f"all slots uncovered as expected (everyone else is out) ({len(result2['uncovered_slots'])}/{len(t1_slots)})")

    # --- manually assign the uncovered slot ---
    uncovered = result2["uncovered_slots"][0]
    r = req("POST", "/substitutions", token=sa_token, json={
        "leave_id": leave2_id, "timetable_id": uncovered["timetable_id"],
        "substitute_teacher_id": t2_id, "date": uncovered["date"],
    })
    check(r.status_code == 201, f"manual substitution for uncovered slot ({r.text if r.status_code != 201 else ''})")
    manual_sub_id = r.json()["id"]
    check(r.json()["method"] == "manual", "manual substitution flagged with method=manual")

    # duplicate manual assignment for the same slot/date should 409
    r = req("POST", "/substitutions", token=sa_token, json={
        "leave_id": leave2_id, "timetable_id": uncovered["timetable_id"],
        "substitute_teacher_id": t3_id, "date": uncovered["date"],
    })
    check(r.status_code == 409, "duplicate manual assignment for same slot/date is rejected (409)")

    r = req("PUT", f"/substitutions/{manual_sub_id}", token=sa_token, json={"substitute_teacher_id": t3_id})
    check(r.status_code == 200, "reassign manual substitution to a different teacher")

    r = req("DELETE", f"/substitutions/{manual_sub_id}", token=sa_token)
    check(r.status_code == 204, "delete manual substitution")

    # --- rejection flow ---
    r = req("POST", "/leaves", token=t1_token, json={"date": str(leave_date2 + datetime.timedelta(days=7)), "reason": "Third"})
    leave4_id = r.json()["id"]
    r = req("POST", f"/leaves/{leave4_id}/reject", token=sa_token, json={"note": "Not enough notice"})
    check(r.status_code == 200 and r.json()["status"] == "rejected", "reject a leave request")

    # --- cancel own pending leave ---
    r = req("POST", "/leaves", token=t1_token, json={"date": str(leave_date2 + datetime.timedelta(days=14)), "reason": "Fourth"})
    leave5_id = r.json()["id"]
    r = req("DELETE", f"/leaves/{leave5_id}", token=t1_token)
    check(r.status_code == 204, "teacher cancels own pending leave")

    print("\nALL PHASE 4 TESTS PASSED")


if __name__ == "__main__":
    main()
