"""
Seed "Demo Government Higher Secondary School" from SCHOOL_SEED_CONFIGURATION.md
and generate its master timetable.

DESTRUCTIVE: truncates every table first.

Layout
    8 periods/day x 5 days      = 40 slots per section
    38 teaching periods         + 2 fixed (Fri P7/P8 Personal Talent Development)
    -> every section is EXACTLY full; there is zero slack.

Mathematics and Science need 7 periods across a 5-day week, so
`double_periods_allowed` must be on (max 2 lessons of a subject per day).

Fixed events are modelled as LOCKED timetable rows: the generator treats locked
slots as immovable pre-assignments and never schedules over them.

Usage:
    python -m uvicorn app.main:app --port 8010     # server must be running
    python seed_demo_school.py
"""
import json
import os
import sys
import time
import collections

import requests
from sqlalchemy import text

from app.database import SessionLocal, engine, Base
from app import models
from app.auth import hash_password

BASE = os.environ.get("EDUFLOW_BASE_URL", "http://127.0.0.1:8010").rstrip("/")
ADMIN_EMAIL, ADMIN_PASSWORD = "admin@school.edu", "Admin@123"
TEACHER_PASSWORD = "12345678"

# ---------------------------------------------------------------- source data
SCHOOL_NAME = "Demo Government Higher Secondary School"
PPD, WD = 8, 5
FRIDAY = 4  # Monday = 0

STRUCTURE = {
    "6": ["A", "B"],
    "7": ["A", "B"],
    "8": ["A", "B"],
    "9": ["A1", "A2", "B", "C"],
    "10": ["A1", "A2", "B", "C"],
}

HOURS = {
    "Tamil": 6, "English": 6, "Mathematics": 7, "Science": 7, "Social Science": 6,
    "PET": 2, "Library": 1, "Drawing": 1, "Music": 1, "Value Education": 1,
}

TEACHERS = [
    "Mani", "Meinyanavalli", "Thulasimani", "Jaya", "Lingeshwari", "Subbu", "Valli",
    "Vanitha", "Kavitha", "Kannan Prakash", "Sangeetha", "Rukmani", "Annakili", "Sasi",
    "Sankara Gomathi", "Jaya Chitra", "Siva Kumar", "Padma", "Uma", "Arthi", "Selvi",
    "Jaya Pratha", "Hellen", "Santhiya",
]

CLASS_TEACHERS = {
    "6A": "Rukmani", "6B": "Sankara Gomathi", "7A": "Kannan Prakash", "7B": "Subbu",
    "8A": "Jaya", "8B": "Meinyanavalli", "9A1": "Lingeshwari", "9A2": "Annakili",
    "9B": "Sangeetha", "9C": "Vanitha", "10A1": "Thulasimani", "10A2": "Sasi",
    "10B": "Kavitha", "10C": "Valli",
}

ALL = ["6A", "6B", "7A", "7B", "8A", "8B", "9A1", "9A2", "9B", "9C", "10A1", "10A2", "10B", "10C"]

# (section, subject) -> teacher.  Exactly one teacher per pair.
ALLOC = {}


def put(subject, mapping):
    for sec, teacher in mapping.items():
        key = (sec, subject)
        if key in ALLOC:
            raise SystemExit(f"Duplicate allocation for {sec} {subject}")
        ALLOC[key] = teacher


put("Mathematics", {
    "6A": "Meinyanavalli", "6B": "Thulasimani", "7A": "Kannan Prakash", "7B": "Subbu",
    "8A": "Kannan Prakash", "8B": "Thulasimani", "9A1": "Kannan Prakash", "9A2": "Meinyanavalli",
    "9B": "Arthi", "9C": "Thulasimani", "10A1": "Thulasimani", "10A2": "Meinyanavalli",
    "10B": "Subbu", "10C": "Kannan Prakash",
})
put("Tamil", {
    "6A": "Padma", "6B": "Lingeshwari", "7A": "Arthi", "7B": "Arthi", "8A": "Padma",
    "8B": "Meinyanavalli", "9A1": "Valli", "9A2": "Vanitha", "9B": "Valli", "9C": "Vanitha",
    "10A1": "Vanitha", "10A2": "Valli", "10B": "Vanitha", "10C": "Valli",
})
# 6A English -> Lingeshwari (the source doc allocated it to both her and Rukmani).
put("English", {
    "6A": "Lingeshwari", "6B": "Sankara Gomathi", "7A": "Rukmani", "7B": "Sankara Gomathi",
    "8A": "Jaya Chitra", "8B": "Jaya", "9A1": "Lingeshwari", "9A2": "Sankara Gomathi",
    "9B": "Jaya", "9C": "Rukmani", "10A1": "Lingeshwari", "10A2": "Sankara Gomathi",
    "10B": "Jaya", "10C": "Rukmani",
})
put("Science", {
    "6A": "Selvi", "6B": "Sasi", "7A": "Sasi", "7B": "Sangeetha", "8A": "Jaya Pratha",
    "8B": "Hellen", "9A1": "Kavitha", "9A2": "Selvi", "9B": "Sangeetha", "9C": "Sasi",
    "10A1": "Kavitha", "10A2": "Sasi", "10B": "Kavitha", "10C": "Sangeetha",
})
put("Social Science", {
    "6A": "Rukmani", "6B": "Sangeetha", "7A": "Mani", "7B": "Selvi", "8A": "Jaya",
    "8B": "Santhiya", "9A1": "Mani", "9A2": "Annakili", "9B": "Santhiya", "9C": "Annakili",
    "10A1": "Mani", "10A2": "Annakili", "10B": "Mani", "10C": "Annakili",
})
put("PET", {s: "Uma" for s in ALL})
put("Music", {s: "Padma" for s in ALL})
put("Drawing", {s: "Siva Kumar" for s in ALL})
put("Library", {
    **{s: "Siva Kumar" for s in ["6A", "6B", "7A", "7B", "8A", "8B", "9A1", "9B", "9C"]},
    "9A2": "Annakili", "10A1": "Thulasimani", "10A2": "Sasi", "10B": "Jaya", "10C": "Annakili",
})
put("Value Education", {
    "6A": "Jaya", "6B": "Lingeshwari", "7A": "Lingeshwari", "7B": "Siva Kumar",
    "8A": "Jaya", "8B": "Mani", "9A1": "Lingeshwari", "9A2": "Meinyanavalli",
    "9B": "Annakili", "9C": "Arthi", "10A1": "Kavitha", "10A2": "Meinyanavalli",
    "10B": "Kavitha", "10C": "Sangeetha",
})

MAX_WEEKLY_HOURS = 30


def email_for(name: str) -> str:
    return name.lower().replace(" ", "") + "@school.edu"


# ---------------------------------------------------------------- preflight
def preflight():
    print("== Preflight ==")
    problems = []
    for sec in ALL:
        missing = [s for s in HOURS if (sec, s) not in ALLOC]
        if missing:
            problems.append(f"{sec} missing: {', '.join(missing)}")
    if len(ALLOC) != len(ALL) * len(HOURS):
        problems.append(f"expected {len(ALL)*len(HOURS)} allocations, have {len(ALLOC)}")

    load = collections.Counter()
    for (sec, subj), t in ALLOC.items():
        load[t] += HOURS[subj]
    over = {t: h for t, h in load.items() if h > MAX_WEEKLY_HOURS}
    if over:
        problems.append(f"over {MAX_WEEKLY_HOURS}h cap: {over}")

    teach = sum(HOURS.values())
    if teach + 2 > PPD * WD:
        problems.append(f"{teach}+2 periods exceed {PPD*WD} slots")
    if sum(load.values()) != len(ALL) * teach:
        problems.append(f"load {sum(load.values())} != {len(ALL)*teach}")

    unknown = set(load) - set(TEACHERS)
    if unknown:
        problems.append(f"unknown teachers: {unknown}")

    print(f"  allocations      : {len(ALLOC)}")
    print(f"  total lesson-slots: {sum(load.values())} (= {len(ALL)} x {teach})")
    print(f"  busiest teacher  : {max(load.items(), key=lambda x: x[1])}")
    print(f"  idle teachers    : {sorted(set(TEACHERS) - set(load)) or 'none'}")
    if problems:
        print("\nPREFLIGHT FAILED:")
        for p in problems:
            print("  -", p)
        sys.exit(1)
    print("  OK\n")
    return load


# ---------------------------------------------------------------- wipe
def wipe():
    print("== Wiping every table (irreversible) ==")
    Base.metadata.create_all(bind=engine)
    tables = [t.name for t in reversed(Base.metadata.sorted_tables)]
    with engine.begin() as conn:
        if engine.dialect.name == "postgresql":
            conn.execute(text(f"TRUNCATE TABLE {', '.join(tables)} RESTART IDENTITY CASCADE"))
        else:
            for t in tables:
                conn.execute(text(f"DELETE FROM {t}"))
    print(f"  {len(tables)} tables truncated\n")


def seed_admins():
    db = SessionLocal()
    for email, name in ((ADMIN_EMAIL, "School Admin"), ("admin@eduflow.com", "Super Admin")):
        db.add(models.User(name=name, email=email, hashed_password=hash_password(ADMIN_PASSWORD),
                           role=models.RoleEnum.super_admin, is_active=True))
    db.commit()
    db.close()
    print(f"  admins: {ADMIN_EMAIL} and admin@eduflow.com (both {ADMIN_PASSWORD})\n")


# ---------------------------------------------------------------- api helpers
S = requests.Session()
TOK = None


def api(method, path, **kw):
    h = {"Authorization": f"Bearer {TOK}"} if TOK else {}
    r = S.request(method, f"{BASE}{path}", headers=h, timeout=600, **kw)
    if r.status_code >= 300:
        raise SystemExit(f"{method} {path} -> {r.status_code}: {r.text[:300]}")
    try:
        return r.json()
    except Exception:
        return {}


def main():
    global TOK
    load = preflight()

    try:
        requests.get(f"{BASE}/health", timeout=5)
    except Exception:
        sys.exit(f"Server not reachable at {BASE}. Start uvicorn first.")

    wipe()
    seed_admins()

    TOK = api("POST", "/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})["access_token"]
    print("== Building school ==")

    school = api("POST", "/schools", json={"name": SCHOOL_NAME, "periods_per_day": PPD, "working_days": WD})
    SID = school["id"]

    timings, clock = [], 9 * 60
    for p in range(1, PPD + 1):
        if p == 5:
            clock += 40  # lunch after period 4
        start, end = clock, clock + 45
        timings.append({"period": p, "start": f"{start//60:02d}:{start%60:02d}",
                        "end": f"{end//60:02d}:{end%60:02d}"})
        clock = end
    cfg = json.loads(api("GET", f"/schools/{SID}/config")["config"])
    cfg.update({
        "school_type": "Government",
        "academic_year": "2026-2027",
        "period_timings": timings,
        "teacher_assignment_method": "manual",
        "subject_configuration": {"hours_defined_at": "per_class"},
        "resources": {"enabled": False},
        "activities": {"enabled": True, "list": ["Personal Talent Development"]},
        "teacher_eligibility": {"enabled": False, "groups": []},
        "mediums": {"enabled": False, "list": []},
        # Mathematics/Science need 7 periods across 5 days -> 2 lessons/day allowed.
        #
        # Daily core coverage: core subjects total 32 periods/week, so max_core_per_day
        # must be >= 7 (6 x 5 days = 30 < 32). A cap of 2/day would need 30 non-core
        # periods per week and only 6 exist -- see the linter in timetable_generator.
        #
        # class_teacher_double_period: the class teacher takes P1+P2 on one day of the week,
        # teaching a subject already allocated to them. The solver picks the day.
        #
        # core_subject_daily_min: every core subject appears at least once, every day, in every
        # section. Requires each core teacher to be available on all 5 days.
        "scheduling_policies": {"double_periods_allowed": True,
                                "max_consecutive_periods": 3,
                                "max_daily_periods": 8,
                                "core_subjects": ["Tamil", "English", "Mathematics",
                                                  "Science", "Social Science"],
                                "min_core_per_day": 1,
                                "max_core_per_day": 7,
                                "core_subject_daily_min": 1,
                                "class_teacher_double_period": True},
        "enabled_modules": ["timetables", "leaves", "swaps", "exams", "reports"],
    })
    api("PUT", f"/schools/{SID}/config", json={"config": json.dumps(cfg)})
    print(f"  school #{SID}, {PPD} periods x {WD} days, lunch after P4, manual allocation")

    subj_id = {n: api("POST", "/subjects", json={"name": n, "weekly_hours": h, "school_id": SID})["id"]
               for n, h in HOURS.items()}
    print(f"  {len(subj_id)} subjects")

    ptd = api("POST", "/activities", json={"name": "Personal Talent Development",
                                           "weekly_hours": 2, "school_id": SID})["id"]
    print("  activity: Personal Talent Development (2h, fixed Fri P7-P8)")

    teacher_id = {}
    for name in TEACHERS:
        subs = sorted({s for (sec, s), t in ALLOC.items() if t == name})
        teacher_id[name] = api("POST", "/teachers", json={
            "name": name, "email": email_for(name), "password": TEACHER_PASSWORD,
            "department": subs[0] if subs else None, "max_weekly_hours": MAX_WEEKLY_HOURS,
            "school_id": SID, "subject_ids": [subj_id[s] for s in subs],
        })["id"]
    print(f"  {len(teacher_id)} teachers (password {TEACHER_PASSWORD})")

    section_id = {}
    for grade, secs in STRUCTURE.items():
        cid = api("POST", "/classes", json={"name": grade, "school_id": SID})["id"]
        payload = [{"name": s, "class_teacher_id": teacher_id[CLASS_TEACHERS[grade + s]]} for s in secs]
        for row in api("POST", "/sections/bulk", json={"class_id": cid, "sections": payload}):
            section_id[grade + row["name"]] = row["id"]
    print(f"  {len(section_id)} sections with class teachers")

    for (sec, subj), t in ALLOC.items():
        api("POST", "/assignments", json={"section_id": section_id[sec], "subject_id": subj_id[subj],
                                          "teacher_id": teacher_id[t], "school_id": SID})
    print(f"  {len(ALLOC)} per-section subject-teacher allocations")

    # Fixed event -> locked rows the solver must schedule around.
    db = SessionLocal()
    for sec in ALL:
        for period in (7, 8):
            db.add(models.Timetable(school_id=SID, section_id=section_id[sec], activity_id=ptd,
                                    day_of_week=FRIDAY, period=period, is_locked=True))
    db.commit()
    db.close()
    print(f"  {len(ALL)*2} locked PTD slots (Friday P7 & P8)\n")

    print("== Validation ==")
    v = api("GET", f"/validation/school/{SID}")
    print(f"  readiness={v.get('readiness_score')}  ready_to_generate={v.get('ready_to_generate')}\n")

    print("== Generating timetable ==")
    t0 = time.time()
    api("POST", "/timetables/generate", json={"school_id": SID, "time_limit_seconds": 300})
    print(f"  solved in {time.time()-t0:.1f}s\n")

    rows = []
    for sec, sec_id in section_id.items():
        page = 1
        while True:
            j = api("GET", "/timetables", params={"section_id": sec_id, "limit": 200, "page": page})
            rows += j["items"]
            if len(j["items"]) < 200:
                break
            page += 1

    print("== Verifying ==")
    ok = True

    def chk(name, cond, detail=""):
        nonlocal ok
        ok = ok and cond
        print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" -> {detail}" if not cond and detail else ""))

    lessons = [r for r in rows if r.get("subject_id")]
    fixed = [r for r in rows if r.get("activity_id")]
    chk(f"total rows == {len(ALL)*PPD*WD}", len(rows) == len(ALL) * PPD * WD, len(rows))
    chk(f"teaching lessons == {len(ALL)*sum(HOURS.values())}", len(lessons) == len(ALL) * sum(HOURS.values()), len(lessons))
    chk(f"fixed PTD slots == {len(ALL)*2}", len(fixed) == len(ALL) * 2, len(fixed))
    chk("all PTD on Friday P7/P8", all(r["day_of_week"] == FRIDAY and r["period"] in (7, 8) for r in fixed))
    chk("no academic lesson in a PTD slot",
        not [r for r in lessons if r["day_of_week"] == FRIDAY and r["period"] in (7, 8)])

    sec_slot = collections.Counter((r["section_id"], r["day_of_week"], r["period"]) for r in rows)
    chk("no class clash", all(v == 1 for v in sec_slot.values()))
    tch_slot = collections.Counter((r["teacher_id"], r["day_of_week"], r["period"]) for r in lessons)
    chk("no teacher clash", all(v == 1 for v in tch_slot.values()),
        [k for k, v in tch_slot.items() if v > 1][:3])

    hrs = collections.Counter((r["section_id"], r["subject_name"]) for r in lessons)
    chk("weekly hours exact for every section/subject",
        all(hrs.get((section_id[s], sub), 0) == h for s in ALL for sub, h in HOURS.items()))

    wrong = [(r["section_name"], r["subject_name"], r["teacher_name"]) for r in lessons
             if r["teacher_name"] != ALLOC.get((r["section_name"].replace(" ", ""), r["subject_name"]))]
    chk("every lesson taught by the allocated teacher", not wrong, wrong[:3])

    tload = collections.Counter(r["teacher_name"] for r in lessons)
    chk(f"no teacher over {MAX_WEEKLY_HOURS}h", all(v <= MAX_WEEKLY_HOURS for v in tload.values()), dict(tload))
    chk("teacher loads match the spec", all(tload[t] == load[t] for t in load),
        {t: (tload[t], load[t]) for t in load if tload[t] != load[t]})

    spread = collections.Counter((r["section_id"], r["subject_id"], r["day_of_week"]) for r in lessons)
    chk("no subject more than twice a day", all(v <= 2 for v in spread.values()))

    print(f"\nSchool #{SID} — {SCHOOL_NAME}")
    print(f"Login: {ADMIN_EMAIL} / {ADMIN_PASSWORD}   Teachers: <firstname>@school.edu / {TEACHER_PASSWORD}")
    print(f"View: {BASE}/app/timetable.html")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
