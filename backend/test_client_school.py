"""
Client acceptance test: build the admin's ACTUAL school and generate a timetable.

  Classes/sections: 6 A,B | 7 A,B | 8 A,B | 9 A1,A2,B,C | 10 A1,A2,B,C   (14 sections)
  Medium: A-series (A, A1, A2) = English; everything else (B, C) = Tamil
  Class teacher per section
  Subjects: Tamil, English, Maths, Science, Social Science
  Teacher allocated PER class-section PER subject (manual mode)
  Per-teacher max hours; per-teacher unavailability for a specific hour
"""
import sys, os, random, collections, requests

BASE = os.environ.get("EDUFLOW_BASE_URL", "http://127.0.0.1:8010").rstrip("/")
RUN = random.randint(10000, 99999)
S = requests.Session()
results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond)))
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f"\n         -> {str(detail)[:240]}" if not cond and detail else ""))
    return bool(cond)


def req(m, p, tok=None, **kw):
    h = kw.pop("headers", {})
    if tok:
        h["Authorization"] = f"Bearer {tok}"
    return S.request(m, f"{BASE}{p}", headers=h, timeout=180, **kw)


def jn(r):
    try:
        return r.json()
    except Exception:
        return {}


import json

print("\n=== LOGIN ===")
r = req("POST", "/auth/login", json={"email": "admin@eduflow.com", "password": "Admin@123"})
if r.status_code != 200:
    print("cannot login"); sys.exit(1)
TOK = jn(r)["access_token"]
check("admin login", True)

# ---------------------------------------------------------------- school + config
print("\n=== SCHOOL + CONFIG (mediums on, manual teacher allocation) ===")
PPD, WD = 8, 5   # 8 periods x 5 days = 40 slots/section
r = req("POST", "/schools", TOK, json={"name": f"ClientSchool-{RUN}", "periods_per_day": PPD, "working_days": WD})
SID = jn(r).get("id")
check("create school", r.status_code < 300, r.text)

cfg = json.loads(jn(req("GET", f"/schools/{SID}/config", TOK))["config"])
cfg["mediums"] = {"enabled": True, "list": ["English", "Tamil"]}
cfg["teacher_assignment_method"] = "manual"
cfg["subject_configuration"] = {"hours_defined_at": "per_class"}
cfg["resources"] = {"enabled": False}
cfg["activities"] = {"enabled": False, "list": []}
cfg["teacher_eligibility"] = {"enabled": False, "groups": []}
cfg["scheduling_policies"] = {}          # default: max 1 lesson/subject/day
r = req("PUT", f"/schools/{SID}/config", TOK, json={"config": json.dumps(cfg)})
check("config saved (mediums enabled, manual mode)", r.status_code < 300, r.text)

# ---------------------------------------------------------------- teachers
print("\n=== TEACHERS (per-subject pools, custom max hours) ===")
SUBJECTS = ["Tamil", "English", "Maths", "Science", "Social Science"]
HOURS = {"Tamil": 5, "English": 5, "Maths": 5, "Science": 5, "Social Science": 5}  # 25 <= 40

# 14 sections x 5h = 70h per subject. Cap 25h/teacher -> need >=3 teachers per subject.
TEACHERS = {}       # subject -> [teacher_id...]
TEACHER_NAME = {}
for subj in SUBJECTS:
    TEACHERS[subj] = []
    for n in range(1, 4):
        slug = subj.lower().replace(" ", "")
        r = req("POST", "/teachers", TOK, json={
            "name": f"{subj} Teacher {n}", "email": f"{slug}{n}.{RUN}@example.com",
            "password": "Teach@1234", "department": subj,
            "max_weekly_hours": 25, "school_id": SID,
        })
        if r.status_code >= 300:
            check(f"create teacher {subj}{n}", False, r.text); continue
        tid = jn(r)["id"]
        TEACHERS[subj].append(tid)
        TEACHER_NAME[tid] = f"{subj} Teacher {n}"
check("15 teachers created (3 per subject)", sum(len(v) for v in TEACHERS.values()) == 15)

# per-teacher max hours is editable
t0 = TEACHERS["Maths"][0]
r = req("PUT", f"/teachers/{t0}", TOK, json={"max_weekly_hours": 26})
check("REQ: per-teacher max hours can be modified", r.status_code < 300 and jn(r).get("max_weekly_hours") == 26, r.text)
# clearing the field must NOT null the column (the scheduler does arithmetic on it)
r = req("PUT", f"/teachers/{t0}", TOK, json={"max_weekly_hours": None})
check("clearing max hours leaves value intact (no NULL)", jn(r).get("max_weekly_hours") == 26, jn(r).get("max_weekly_hours"))
r = req("PUT", f"/teachers/{t0}", TOK, json={"max_weekly_hours": 0})
check("zero max hours rejected (422)", r.status_code == 422, r.status_code)

# ---------------------------------------------------------------- subjects
print("\n=== SUBJECTS ===")
SUBJ = {}
for s in SUBJECTS:
    r = req("POST", "/subjects", TOK, json={"name": s, "weekly_hours": HOURS[s], "school_id": SID})
    SUBJ[s] = jn(r).get("id")
    check(f"subject {s} ({HOURS[s]}h)", r.status_code < 300, r.text)
check(f"per-section demand {sum(HOURS.values())} <= {PPD*WD} slots", sum(HOURS.values()) <= PPD * WD)

# ---------------------------------------------------------------- classes + sections
print("\n=== CLASSES -> SECTIONS (her exact structure, atomic bulk create) ===")
STRUCTURE = {"Class 6": ["A", "B"], "Class 7": ["A", "B"], "Class 8": ["A", "B"],
             "Class 9": ["A1", "A2", "B", "C"], "Class 10": ["A1", "A2", "B", "C"]}


def medium_for(section_name):
    """Her rule: A-series is English medium; everything else Tamil."""
    return "English" if section_name.upper().startswith("A") else "Tamil"


all_teacher_ids = [t for v in TEACHERS.values() for t in v]
SECTIONS = []       # list of dicts
ct_cursor = 0
for cname, secs in STRUCTURE.items():
    r = req("POST", "/classes", TOK, json={"name": cname, "school_id": SID})
    check(f"create {cname}", r.status_code < 300, r.text)
    cid = jn(r).get("id")

    payload = []
    for s in secs:
        payload.append({
            "name": s,
            "medium": medium_for(s),
            "class_teacher_id": all_teacher_ids[ct_cursor % len(all_teacher_ids)],
        })
        ct_cursor += 1
    r = req("POST", "/sections/bulk", TOK, json={"class_id": cid, "sections": payload})
    ok = check(f"bulk-create {len(secs)} sections for {cname}", r.status_code < 300, r.text)
    if ok:
        SECTIONS.extend(jn(r))

check("14 sections total", len(SECTIONS) == 14, len(SECTIONS))

# REQ: medium correctness
eng = [s for s in SECTIONS if s["medium"] == "English"]
tam = [s for s in SECTIONS if s["medium"] == "Tamil"]
# A-series = 6A,7A,8A,9A1,9A2,10A1,10A2 = 7 ; non-A = 6B,7B,8B,9B,9C,10B,10C = 7
check("REQ: A-series sections are English medium",
      all(s["name"].upper().startswith("A") for s in eng) and len(eng) == 7, [s["name"] for s in eng])
check("REQ: B/C sections are Tamil medium",
      all(not s["name"].upper().startswith("A") for s in tam) and len(tam) == 7, [s["name"] for s in tam])

# REQ: class teacher
check("REQ: every section has a class teacher", all(s["class_teacher_id"] for s in SECTIONS))
check("REQ: class teacher name returned for display", all(s["class_teacher_name"] for s in SECTIONS))

# REQ: 6A vs 7A distinguishable
names = sorted(s["display_name"] for s in SECTIONS)
check("REQ: sections carry class name (6 A vs 7 A distinguishable)",
      "Class 6 A" in names and "Class 7 A" in names and len(set(names)) == 14, names[:4])

# atomicity + duplicate guard
c6 = next(s for s in SECTIONS if s["class_name"] == "Class 6")
r = req("POST", "/sections/bulk", TOK, json={"class_id": c6["class_id"], "sections": [{"name": "A"}]})
check("duplicate section rejected (409)", r.status_code == 409, f"{r.status_code} {r.text[:80]}")
r = req("POST", "/sections/bulk", TOK, json={"class_id": c6["class_id"], "sections": [{"name": "Z", "medium": "French"}]})
check("unconfigured medium rejected (400)", r.status_code == 400, f"{r.status_code} {r.text[:90]}")
r = req("GET", "/sections", TOK, params={"school_id": SID, "limit": 200})
check("failed bulk created nothing (atomic)", jn(r).get("total") == 14, jn(r).get("total"))

# medium filter
r = req("GET", "/sections", TOK, params={"school_id": SID, "medium": "English", "limit": 200})
check("filter sections by medium", jn(r).get("total") == 7, jn(r).get("total"))

# ---------------------------------------------------------------- assignments
print("\n=== PER-SECTION TEACHER ALLOCATION (she picks who teaches each section) ===")
# Spread each subject's 14 sections across its 3 teachers (<=5 sections x 5h = 25h cap).
alloc = {}
for subj in SUBJECTS:
    pool = TEACHERS[subj]
    for i, sec in enumerate(SECTIONS):
        tid = pool[i % len(pool)]
        alloc[(sec["id"], subj)] = tid
        r = req("POST", "/assignments", TOK, json={
            "section_id": sec["id"], "subject_id": SUBJ[subj], "teacher_id": tid, "school_id": SID})
        if r.status_code >= 300:
            check(f"assign {subj} -> {sec['display_name']}", False, r.text)
check(f"REQ: {len(SECTIONS)*len(SUBJECTS)} per-section subject-teacher allocations", len(alloc) == 70)

load = collections.Counter(alloc.values())
check("no teacher allocated beyond 25h cap", all(c * 5 <= 25 for c in load.values()), dict(load))

# ---------------------------------------------------------------- availability
print("\n=== TEACHER UNAVAILABLE FOR A PARTICULAR HOUR ===")
BUSY = TEACHERS["Maths"][0]     # unavailable Wednesday(2) period 4
grid = [{"day_of_week": d, "period": p, "is_available": not (d == 2 and p == 4)}
        for d in range(WD) for p in range(1, PPD + 1)]
r = req("PUT", f"/teachers/{BUSY}/availability", TOK, json=grid)
check("set unavailability (Wed period 4)", r.status_code < 300, r.text)
blocked = [a for a in jn(req("GET", f"/teachers/{BUSY}/availability", TOK)) if not a["is_available"]]
check("REQ: unavailability persisted", len(blocked) == 1 and blocked[0]["day_of_week"] == 2 and blocked[0]["period"] == 4, blocked)

# ---------------------------------------------------------------- generate
print("\n=== GENERATE TIMETABLE ===")
import time
t0 = time.time()
r = req("POST", "/timetables/generate", TOK, json={"school_id": SID, "time_limit_seconds": 90})
ms = int((time.time() - t0) * 1000)
gen_ok = check(f"REQ: timetable generated ({ms}ms)", r.status_code < 300, r.text)


def fetch_rows():
    out = []
    for s in SECTIONS:
        j = jn(req("GET", "/timetables", TOK, params={"section_id": s["id"], "limit": 200}))
        out += j.get("items", [])
    return out


rows = fetch_rows() if gen_ok else []
expected = len(SECTIONS) * sum(HOURS.values())
check(f"row count == demand ({expected})", len(rows) == expected, len(rows))

# ---- hard invariants (independent checker) ----
sec_slot = collections.Counter((r_["section_id"], r_["day_of_week"], r_["period"]) for r_ in rows)
tch_slot = collections.Counter((r_["teacher_id"], r_["day_of_week"], r_["period"]) for r_ in rows if r_.get("teacher_id"))
hours = collections.Counter((r_["section_id"], r_["subject_id"]) for r_ in rows)
tload = collections.Counter(r_["teacher_id"] for r_ in rows if r_.get("teacher_id"))

check("HARD: no section double-booked", all(v == 1 for v in sec_slot.values()))
check("HARD: no teacher in two sections at once", all(v == 1 for v in tch_slot.values()),
      [k for k, v in tch_slot.items() if v > 1][:3])
check("HARD: exact weekly hours per subject per section",
      all(hours.get((s["id"], SUBJ[sub]), 0) == HOURS[sub] for s in SECTIONS for sub in SUBJECTS))
check("HARD: teacher weekly caps respected", all(v <= 25 for v in tload.values()), dict(tload))

# REQ: her exact allocation was honoured — the assigned teacher actually teaches that section
mismatch = [(r_["section_id"], r_["subject_name"], r_["teacher_name"])
            for r_ in rows
            if alloc.get((r_["section_id"], r_["subject_name"])) != r_["teacher_id"]]
check("REQ: each section's subject is taught by the teacher she allocated", not mismatch, mismatch[:3])

# REQ: unavailability honoured
viol = [r_ for r_ in rows if r_.get("teacher_id") == BUSY and r_["day_of_week"] == 2 and r_["period"] == 4]
check("REQ: unavailable hour left free for that teacher", not viol, viol[:2])

# subject spread: at most 1 lesson of a subject per section per day
spread = collections.Counter((r_["section_id"], r_["subject_id"], r_["day_of_week"]) for r_ in rows)
check("subject spread respected (<=1/day)", all(v <= 1 for v in spread.values()))

# ---------------------------------------------------------------- capacity linter
print("\n=== CAPACITY LINTER (names the teacher, not a vague failure) ===")
squeeze = TEACHERS["Tamil"][0]
sq_load = sum(1 for _k, v in alloc.items() if v == squeeze) * HOURS["Tamil"]
r = req("PUT", f"/teachers/{squeeze}", TOK, json={"max_weekly_hours": max(1, sq_load - 5)})
check("lower a teacher's cap below their allocation", r.status_code < 300, r.text)
r = req("POST", "/timetables/generate", TOK, json={"school_id": SID, "time_limit_seconds": 30})
msg = str(jn(r).get("detail", ""))
check("over-allocated teacher rejected with 4xx", 400 <= r.status_code < 500, r.status_code)
check("error names the specific teacher", "Tamil Teacher 1" in msg, msg[:170])
check("error is actionable", ("max weekly hours" in msg or "another teacher" in msg), msg[:170])
req("PUT", f"/teachers/{squeeze}", TOK, json={"max_weekly_hours": 25})
check("restore cap -> generates again",
      req("POST", "/timetables/generate", TOK, json={"school_id": SID, "time_limit_seconds": 90}).status_code < 300)

print("\n" + "=" * 70)
P = sum(1 for _, o in results if o)
F = len(results) - P
print(f"TOTAL: {P} passed, {F} failed, {len(results)} checks")
print(f"\nSchool id = {SID}  (name ClientSchool-{RUN})")
if F:
    print("\nFAILURES:")
    for n, o in results:
        if not o:
            print("  -", n)
sys.exit(1 if F else 0)
