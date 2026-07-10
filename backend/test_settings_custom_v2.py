import requests
import random

API_BASE = "http://localhost:8000"

def test_settings_custom():
    print("Starting settings & custom config v2 tests...")
    
    # --- 0. Initialize DB and insert a super admin ---
    suffix = random.randint(10000, 99999)
    from app.database import SessionLocal, Base, engine
    from app import models
    from app.auth import hash_password
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    sa_email = f"customtest.superadmin.{suffix}@example.com"
    sa = models.User(name="CustomTest SuperAdmin", email=sa_email,
                      hashed_password=hash_password("pass1234"), role=models.RoleEnum.super_admin)
    db.add(sa)
    db.commit()
    db.close()

    # --- 1. Super Admin login ---
    r = requests.post(f"{API_BASE}/auth/login", json={"email": sa_email, "password": "pass1234"})
    assert r.status_code == 200, "Super admin login failed"
    sa_token = r.json()["access_token"]
    headers = {"Authorization": f"Bearer {sa_token}"}

    # --- 2. Create school ---
    r = requests.post(f"{API_BASE}/schools", headers=headers, json={"name": f"Config Test School {suffix}", "periods_per_day": 8, "working_days": 5})
    assert r.status_code == 201, "School creation failed"
    school_id = r.json()["id"]

    # --- 3. Get Default Config and verify new configuration properties ---
    r = requests.get(f"{API_BASE}/schools/{school_id}/config", headers=headers)
    assert r.status_code == 200, "Get config failed"
    config = r.json()
    config_data = config["config"]
    import json
    cfg = json.loads(config_data)

    print("Checking default config properties...")
    assert "academic_year" in cfg, "Default config missing academic_year"
    assert "period_timings" in cfg, "Default config missing period_timings"
    assert "enabled_modules" in cfg, "Default config missing enabled_modules"
    assert cfg["academic_year"] == "2026-2027", "Default academic_year mismatch"
    assert len(cfg["period_timings"]) == 8, "Default period timings count mismatch"
    assert "timetables" in cfg["enabled_modules"], "Default enabled modules missing timetables"

    # --- 4. Update school config custom values ---
    cfg["academic_year"] = "2027-2028"
    cfg["enabled_modules"] = ["timetables", "leaves"]
    cfg["period_timings"][0]["start"] = "09:00"
    cfg["period_timings"][0]["end"] = "09:45"
    
    r = requests.put(f"{API_BASE}/schools/{school_id}/config", headers=headers, json={"config": json.dumps(cfg)})
    assert r.status_code == 200, "Update config failed"

    # Fetch and check updated values
    r = requests.get(f"{API_BASE}/schools/{school_id}/config", headers=headers)
    assert r.status_code == 200
    cfg_updated = json.loads(r.json()["config"])
    assert cfg_updated["academic_year"] == "2027-2028", "Updated academic_year mismatch"
    assert cfg_updated["enabled_modules"] == ["timetables", "leaves"], "Updated enabled_modules mismatch"
    assert cfg_updated["period_timings"][0]["start"] == "09:00", "Updated timings mismatch"

    # --- 5. Apply Government preset template ---
    print("Testing template presets...")
    r = requests.post(f"{API_BASE}/schools/{school_id}/apply-template", headers=headers, json={"template_name": "Government"})
    assert r.status_code == 200, "Apply template failed"

    # Fetch and check template config preset values
    r = requests.get(f"{API_BASE}/schools/{school_id}/config", headers=headers)
    assert r.status_code == 200
    cfg_tpl = json.loads(r.json()["config"])
    assert cfg_tpl["school_type"] == "Government School", "Template school type mismatch"
    assert cfg_tpl["period_timings"][0]["start"] == "09:30", "Template timings mismatch"
    assert "exams" not in cfg_tpl["enabled_modules"], "Template enabled modules mismatch"
    assert cfg_tpl["scheduling_policies"]["pet_last_periods"] is True, "Template policies mismatch"

    # --- 6. Test Teacher Role accessibility ---
    # Create school admin and teacher for this school
    teacher_payload = {
        "email": f"teacher_config_{suffix}@eduflow.ai",
        "name": "Teacher Config",
        "password": "teacherpassword",
        "role": "teacher",
        "school_id": school_id
    }
    r = requests.post(f"{API_BASE}/teachers", headers=headers, json=teacher_payload)
    assert r.status_code == 201, "Teacher creation failed"
    
    # Login as teacher
    r = requests.post(f"{API_BASE}/auth/login", json={"email": f"teacher_config_{suffix}@eduflow.ai", "password": "teacherpassword"})
    assert r.status_code == 200, "Teacher login failed"
    teacher_token = r.json()["access_token"]
    t_headers = {"Authorization": f"Bearer {teacher_token}"}

    # Teacher GET own school config (should be allowed)
    r = requests.get(f"{API_BASE}/schools/{school_id}/config", headers=t_headers)
    assert r.status_code == 200, "Teacher was rejected from reading own school's configuration"

    # Teacher PUT own school config (should be 403 forbidden)
    r = requests.put(f"{API_BASE}/schools/{school_id}/config", headers=t_headers, json={"config": json.dumps(cfg_tpl)})
    assert r.status_code == 403, "Teacher was allowed to modify configuration"

    print("ALL CONFIG & PRESETS V2 TESTS PASSED SUCCESSFULLY!")

if __name__ == "__main__":
    test_settings_custom()
