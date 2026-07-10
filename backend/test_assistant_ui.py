import requests
import random
import sys

API_BASE = "http://localhost:8000"

def req(method, path, token=None, **kw):
    headers = kw.pop("headers", {})
    if token:
        headers["Authorization"] = f"Bearer ${token}"
    r = requests.request(method, f"{API_BASE}{path}", headers=headers, **kw)
    return r

def check(cond, msg):
    if not cond:
        print(f"FAIL: {msg}")
        sys.exit(1)
    print(f"OK: {msg}")

def test_assistant():
    print("Starting AI Assistant integration tests...")

    # --- 0. Initialize DB and insert super admin ---
    suffix = random.randint(10000, 99999)
    from app.database import SessionLocal, Base, engine
    from app import models
    from app.auth import hash_password
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    sa_email = f"asstest.superadmin.{suffix}@example.com"
    sa = models.User(name="AssTest SuperAdmin", email=sa_email,
                      hashed_password=hash_password("pass1234"), role=models.RoleEnum.super_admin)
    db.add(sa)
    db.commit()
    db.close()

    # --- 1. Login ---
    r = requests.post(f"{API_BASE}/auth/login", json={"email": sa_email, "password": "pass1234"})
    check(r.status_code == 200, "Super admin login")
    token = r.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # --- 2. Create school ---
    r = requests.post(f"{API_BASE}/schools", headers=headers, json={"name": f"Assistant Test School {suffix}", "periods_per_day": 8, "working_days": 5})
    check(r.status_code == 201, "Create school")
    school_id = r.json()["id"]

    # --- 3. Test explain-conflict ---
    print("Testing /assistant/explain-conflict...")
    payload = {
        "detail": "Teacher 'John Doe' is double-booked on Monday Period 3.",
        "context": {"day": "Monday", "period": 3, "teacher": "John Doe"}
    }
    r = requests.post(f"{API_BASE}/assistant/explain-conflict", headers=headers, json=payload)
    print("explain-conflict response:", r.status_code, r.text)
    check(r.status_code == 200, "explain-conflict status")
    explanation = r.json().get("explanation")
    check(explanation and len(explanation) > 10, "explain-conflict returned valid prose")
    print(f"Explanation sample: {explanation[:120]}...")

    # --- 4. Test workload-suggestions ---
    print("Testing /assistant/workload-suggestions...")
    r = requests.get(f"{API_BASE}/assistant/workload-suggestions?school_id={school_id}", headers=headers)
    check(r.status_code == 200, "workload-suggestions status")
    suggestions = r.json().get("suggestions")
    check(suggestions and len(suggestions) > 10, "workload-suggestions returned suggestions text")
    print(f"Suggestions sample: {suggestions[:120]}...")

    # --- 5. Test narrate-report ---
    print("Testing /assistant/narrate-report...")
    # Seed some data to make the report narratable
    # Let's narrate a leave-summary report
    payload = {
        "report_type": "leave-summary",
        "school_id": school_id,
        "start_date": "2026-07-01",
        "end_date": "2026-07-31"
    }
    r = requests.post(f"{API_BASE}/assistant/narrate-report", headers=headers, json=payload)
    check(r.status_code == 200, "narrate-report status")
    narrative = r.json().get("narrative")
    check(narrative and len(narrative) > 10, "narrate-report returned prose narrative")
    print(f"Narrative sample: {narrative[:120]}...")

    # --- 6. Test chat assistant ---
    print("Testing /assistant/chat...")
    payload = {
        "message": "Are there any overloaded teachers or resource capacity issues right now?",
        "school_id": school_id
    }
    r = requests.post(f"{API_BASE}/assistant/chat", headers=headers, json=payload)
    check(r.status_code == 200, "chat assistant status")
    reply = r.json().get("reply")
    check(reply and len(reply) > 10, "chat assistant returned a reply")
    print(f"Chat reply: {reply[:120]}...")

    print("ALL AI ASSISTANT INTEGRATION TESTS PASSED SUCCESSFULLY!")

if __name__ == "__main__":
    test_assistant()
