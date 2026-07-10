import sys
import random
import requests
import time

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
    sa_email = f"enttest.superadmin.{suffix}@example.com"
    sa = models.User(name="Enterprise SuperAdmin", email=sa_email,
                      hashed_password=hash_password("pass1234"), role=models.RoleEnum.super_admin)
    db.add(sa)
    db.commit()
    db.close()

    # 2. Login
    r = req("POST", "/auth/login", json={"email": sa_email, "password": "pass1234"})
    check(r.status_code == 200, "super_admin login")
    sa_token = r.json()["access_token"]

    # 3. Create school
    r = req("POST", "/schools", token=sa_token, json={"name": f"Enterprise School {suffix}", "periods_per_day": 5, "working_days": 5})
    check(r.status_code == 201, "create school")
    school_id = r.json()["id"]

    # 4. Check category-based validation report (Item 3)
    r = req("GET", f"/validation/school/{school_id}", token=sa_token)
    check(r.status_code == 200, "get validation report")
    data = r.json()
    check("category_scores" in data, "report contains category scores")
    check("Configuration" in data["category_scores"], "Configuration category score present")
    check("Assignments" in data["category_scores"], "Assignments category score present")
    check("Teachers" in data["category_scores"], "Teachers category score present")
    check("quality_score" in data, "report contains quality score parameters")

    # 5. Check validation caching & invalidation (Item 13)
    t1 = data["timestamp"]
    time.sleep(0.5)
    r_cache = req("GET", f"/validation/school/{school_id}", token=sa_token)
    t2 = r_cache.json()["timestamp"]
    check(t1 == t2, "caching is active (timestamp is identical)")

    # Invalidate cache
    r_inv = req("POST", f"/validation/school/{school_id}/invalidate", token=sa_token)
    check(r_inv.status_code == 200, "invalidate cache endpoint")

    r_fresh = req("GET", f"/validation/school/{school_id}", token=sa_token)
    t3 = r_fresh.json()["timestamp"]
    check(t1 != t3, "cache successfully invalidated and re-evaluated fresh")

    # 6. Add configuration setup to make school publishable (readiness score >= 80)
    r = req("POST", "/classes", token=sa_token, json={"school_id": school_id, "name": "Grade 11"})
    check(r.status_code == 201, "create class")
    class_id = r.json()["id"]

    r = req("POST", "/sections", token=sa_token, json={"class_id": class_id, "name": "B"})
    check(r.status_code == 201, "create section")
    section_id = r.json()["id"]

    r = req("POST", "/subjects", token=sa_token, json={"school_id": school_id, "name": "Physics", "weekly_hours": 2})
    check(r.status_code == 201, "create subject")
    subject_id = r.json()["id"]

    t_email = f"enttest.t1.{suffix}@example.com"
    r = req("POST", "/teachers", token=sa_token, json={
        "school_id": school_id, "name": "Teacher Physics", "email": t_email, "password": "pass1234",
        "department": "Science", "max_weekly_hours": 15, "subject_ids": [subject_id]
    })
    check(r.status_code == 201, "create teacher")
    teacher_id = r.json()["id"]

    r = req("POST", "/assignments", token=sa_token, json={
        "school_id": school_id, "section_id": section_id, "subject_id": subject_id, "teacher_id": teacher_id
    })
    check(r.status_code == 201, "assign teacher")

    # Re-verify readiness score
    r = req("GET", f"/validation/school/{school_id}", token=sa_token)
    data = r.json()
    check(data["readiness_score"] >= 80, "school readiness score is now high enough for publishing")

    # 7. Test Save Draft with extended metadata (Item 1)
    draft_payload = {
        "school_id": school_id,
        "name": "Revision Alpha",
        "academic_year": "2026-2027",
        "term": "Term 2",
        "semester": "Semester 1",
        "generation_policy": "Dense",
        "reason": "Test migration snapshot"
    }
    r = req("POST", "/timetables/versions/save-draft", token=sa_token, json=draft_payload)
    check(r.status_code == 200, "save draft version with metadata")
    ver = r.json()
    version_id = ver["id"]
    check(ver["academic_year"] == "2026-2027", "academic year saved in metadata")
    check(ver["generation_policy"] == "Dense", "generation policy saved in metadata")
    check(ver["status"] == "draft", "initial version status is draft")

    # 8. Test Review Workflow transitions (Item 7)
    # draft -> under_review
    r = req("POST", f"/timetables/versions/{version_id}/submit-review", token=sa_token)
    check(r.status_code == 200, "submit version for review")
    check(r.json()["status"] == "under_review", "status updated to under_review")

    # under_review -> approved
    r = req("POST", f"/timetables/versions/{version_id}/approve", token=sa_token)
    check(r.status_code == 200, "approve version")
    check(r.json()["status"] == "approved", "status updated to approved")

    # approved -> published
    r = req("POST", f"/timetables/versions/{version_id}/publish", token=sa_token)
    check(r.status_code == 200, "publish approved version (validation succeeds)")

    # Check status transitioned to published
    r = req("GET", f"/timetables/versions?school_id={school_id}", token=sa_token)
    versions = r.json()
    published_ver = next(v for v in versions if v["id"] == version_id)
    check(published_ver["status"] == "published", "version status successfully changed to published")

    # 9. Test structured assistant suggestions (Item 4 & 12)
    sug_payload = {
        "conflicts": [
            {
                "problem": "Teacher John overloaded",
                "reason": "Assigned 24 periods when limit is 20",
                "suggested_fix": "Assign Kumar",
                "auto_fix_available": True,
                "estimated_impact": "Swaps 4 Math slots to Kumar"
            }
        ]
    }
    r = req("POST", "/assistant/suggestions", token=sa_token, json=sug_payload)
    check(r.status_code == 200, "post assistant suggestions")
    sug_data = r.json()
    check("narrative" in sug_data, "suggestions response contains narrative")
    check("suggestions" in sug_data, "suggestions response contains structured suggestions list")
    check(len(sug_data["suggestions"]) > 0, "suggestions list is not empty")
    check(sug_data["suggestions"][0]["confidence_pct"] > 0, "suggestions contain confidence scores")

    print("\nALL ENTERPRISE VALIDATION & VERSIONING WORKFLOW CHECKS PASSED!\n")

if __name__ == "__main__":
    main()
