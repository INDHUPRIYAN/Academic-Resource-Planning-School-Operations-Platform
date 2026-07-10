import sys
import random
import requests

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
    
    # Create super_admin
    sa_email = f"settings.sa.{suffix}@example.com"
    sa = models.User(name="Settings SuperAdmin", email=sa_email,
                      hashed_password=hash_password("pass1234"), role=models.RoleEnum.super_admin)
    db.add(sa)
    db.commit()
    db.close()

    # Login as Super Admin
    r = req("POST", "/auth/login", json={"email": sa_email, "password": "pass1234"})
    check(r.status_code == 200, "super_admin login")
    sa_token = r.json()["access_token"]

    # Create School 1 and School 2
    r = req("POST", "/schools", token=sa_token, json={"name": f"School A {suffix}", "periods_per_day": 6, "working_days": 5})
    check(r.status_code == 201, "create school 1")
    s1_id = r.json()["id"]

    r = req("POST", "/schools", token=sa_token, json={"name": f"School B {suffix}", "periods_per_day": 8, "working_days": 6})
    check(r.status_code == 201, "create school 2")
    s2_id = r.json()["id"]

    # Create School Admin for School 1
    admin_email = f"admin.s1.{suffix}@example.com"
    r = req("POST", "/teachers", token=sa_token, json={
        "school_id": s1_id, "name": "School 1 Admin Teacher", "email": admin_email, "password": "pass1234",
        "department": "Math", "max_weekly_hours": 20, "subject_ids": [],
    })
    check(r.status_code == 201, "create teacher to become school admin")
    teacher1_id = r.json()["id"]

    # Convert teacher to school admin
    db = SessionLocal()
    teacher_user = db.query(models.User).filter(models.User.email == admin_email).first()
    teacher_user.role = models.RoleEnum.school_admin
    db.commit()
    db.close()

    # Create a regular Teacher for School 1
    teacher_email = f"teacher.s1.{suffix}@example.com"
    r = req("POST", "/teachers", token=sa_token, json={
        "school_id": s1_id, "name": "Regular Teacher", "email": teacher_email, "password": "pass1234",
        "department": "Science", "max_weekly_hours": 20, "subject_ids": [],
    })
    check(r.status_code == 201, "create regular teacher")

    # Login as School Admin
    r = req("POST", "/auth/login", json={"email": admin_email, "password": "pass1234"})
    check(r.status_code == 200, "school_admin login")
    print(f"School Admin login response: {r.json()}")
    admin_token = r.json()["access_token"]

    # Login as Regular Teacher
    r = req("POST", "/auth/login", json={"email": teacher_email, "password": "pass1234"})
    check(r.status_code == 200, "teacher login")
    teacher_token = r.json()["access_token"]

    # --- Test 1: school_admin can update settings of their own school (School 1)
    r = req("PUT", f"/schools/{s1_id}", token=admin_token, json={
        "name": f"School A Updated {suffix}", "periods_per_day": 7, "working_days": 5
    })
    if r.status_code != 200:
        print(f"FAILED updating settings: status={r.status_code}, response={r.text}")
    check(r.status_code == 200, "school_admin can update own school settings")
    check(r.json()["name"] == f"School A Updated {suffix}", "school name updated correctly")
    check(r.json()["periods_per_day"] == 7, "periods per day updated correctly")

    # --- Test 2: school_admin CANNOT update settings of another school (School 2)
    r = req("PUT", f"/schools/{s2_id}", token=admin_token, json={
        "name": f"Hacked School B {suffix}", "periods_per_day": 8, "working_days": 6
    })
    check(r.status_code == 403, "school_admin cannot update other school settings (403)")

    # --- Test 3: teacher CANNOT update school settings
    r = req("PUT", f"/schools/{s1_id}", token=teacher_token, json={
        "name": f"Teacher Update {suffix}"
    })
    check(r.status_code == 403, "teacher cannot update school settings (403)")

    # --- Test 4: super_admin can update settings of any school
    r = req("PUT", f"/schools/{s2_id}", token=sa_token, json={
        "name": f"School B Updated {suffix}", "periods_per_day": 9
    })
    check(r.status_code == 200, "super_admin can update any school settings")
    check(r.json()["name"] == f"School B Updated {suffix}", "school B updated by super admin")

    print("\nALL CUSTOM SETTINGS ROUTER CHECKS PASSED")

if __name__ == "__main__":
    main()
