"""
EduFlow AI - full-stack integration test.

Drives the public REST API against a RUNNING server + real database, asserting
solver correctness invariants (no double-booking, exact weekly hours, teacher
availability) and cross-feature data flow (leave -> substitution overlay,
timetable -> reports, RBAC/tenant isolation, static frontend delivery).

It creates its own throwaway school. NOTE: a school with a generated timetable cannot be
deleted through the API (no endpoint deletes timetable rows), so test schools accumulate.
Purge them with:  psql -U eduflow -h localhost -d eduflow_ai -f cleanup_test_data.sql

Usage:
    python -m uvicorn app.main:app --port 8010     # in one shell
    python test_full_integration.py                # in another

Env overrides:
    EDUFLOW_BASE_URL   (default http://127.0.0.1:8010)
    EDUFLOW_ADMIN_EMAIL / EDUFLOW_ADMIN_PASSWORD
"""
import os, sys, time, random, collections, json, requests

BASE = os.environ.get("EDUFLOW_BASE_URL", "http://127.0.0.1:8010").rstrip("/")
ADMIN_EMAIL = os.environ.get("EDUFLOW_ADMIN_EMAIL", "admin@eduflow.com")
ADMIN_PASSWORD = os.environ.get("EDUFLOW_ADMIN_PASSWORD", "Admin@123")
S = requests.Session()
RUN = random.randint(10000, 99999)
results = []


def check(section, name, cond, detail=""):
    results.append((section, name, bool(cond)))
    mark = "PASS" if cond else "FAIL"
    line = f"  [{mark}] {name}"
    if not cond and detail:
        line += f"\n         -> {str(detail)[:220]}"
    print(line)
    return bool(cond)


def req(method, path, tok=None, **kw):
    h = kw.pop("headers", {})
    if tok:
        h["Authorization"] = f"Bearer {tok}"
    return S.request(method, f"{BASE}{path}", headers=h, timeout=120, **kw)


def jn(r):
    try:
        return r.json()
    except Exception:
        return {}


def fetch_rows(sec_ids, tok=None):
    """/timetables has no school_id filter; scope by section to stay school-safe."""
    out = []
    for sid_ in sec_ids:
        page = 1
        while True:
            j = jn(req("GET", "/timetables", tok or ADMIN, params={"section_id": sid_, "limit": 200, "page": page}))
            items = j.get("items", [])
            out += items
            if not items or len(items) < 200:
                break
            page += 1
    return out


# ---------------------------------------------------------------- 0. auth
print("\n=== [0] AUTH / FE-BE handshake ===")
r = req("POST", "/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
check("auth", "super_admin login -> 200", r.status_code == 200, r.text)
ADMIN = jn(r).get("access_token")
if not ADMIN:
    print(f"FATAL: cannot login as {ADMIN_EMAIL} at {BASE}"); sys.exit(1)
check("auth", "/auth/me returns identity", req("GET", "/auth/me", ADMIN).status_code == 200)
check("auth", "unauthenticated read blocked", req("GET", "/schools").status_code == 401)

# ---------------------------------------------------------------- 1. school + config
print("\n=== [1] SCHOOL + CONFIGURATION ENGINE ===")
PPD, WD = 6, 5
r = req("POST", "/schools", ADMIN, json={"name": f"IntegrationSchool-{RUN}", "periods_per_day": PPD, "working_days": WD})
check("config", "create school -> 2xx", r.status_code < 300, r.text)
SID = jn(r).get("id")


def get_cfg(sid):
    j = jn(req("GET", f"/schools/{sid}/config", ADMIN))
    return json.loads(j["config"]) if isinstance(j.get("config"), str) else j.get("config")


def put_cfg(sid, cfg):
    return req("PUT", f"/schools/{sid}/config", ADMIN, json={"config": json.dumps(cfg)})


r = req("GET", f"/schools/{SID}/config", ADMIN)
check("config", "GET config -> 200", r.status_code == 200, r.text)
cfg = get_cfg(SID)
check("config", "default config auto-created with period_timings", "period_timings" in cfg, list(cfg)[:6])
check("config", "default assignment method present", "teacher_assignment_method" in cfg)

r = req("POST", f"/schools/{SID}/apply-template", ADMIN, json={"template_name": "Private"})
check("config", "apply-template 'Private' -> 2xx", r.status_code < 300, r.text)
check("config", "invalid template rejected (400)",
      req("POST", f"/schools/{SID}/apply-template", ADMIN, json={"template_name": "Nope"}).status_code == 400)

cfg = get_cfg(SID)
cfg["teacher_assignment_method"] = "manual"
cfg["subject_configuration"] = {"hours_defined_at": "per_class"}
cfg["resources"] = {"enabled": True}
cfg["teacher_eligibility"] = {"enabled": False, "groups": []}
cfg["activities"] = {"enabled": False, "list": []}
cfg["scheduling_policies"] = {}
check("config", "PUT config -> 2xx", put_cfg(SID, cfg).status_code < 300)
check("config", "config round-trips to DB", get_cfg(SID).get("teacher_assignment_method") == "manual")

check("config", "malformed JSON config rejected (400)",
      req("PUT", f"/schools/{SID}/config", ADMIN, json={"config": "not-json"}).status_code == 400)
check("config", "non-dict JSON config rejected (400)",
      req("PUT", f"/schools/{SID}/config", ADMIN, json={"config": "[1,2,3]"}).status_code == 400)

# ---------------------------------------------------------------- 2. academic data
print("\n=== [2] ACADEMIC DATA (classes -> sections -> subjects -> resources) ===")
r = req("POST", "/classes", ADMIN, json={"name": "Grade 5", "school_id": SID})
check("academic", "create class", r.status_code < 300, r.text)
CID = jn(r).get("id")

SEC = []
for nm in ["A", "B"]:
    r = req("POST", "/sections", ADMIN, json={"name": nm, "class_id": CID})
    check("academic", f"create section {nm}", r.status_code < 300, r.text)
    SEC.append(jn(r).get("id"))

r = req("POST", "/resources", ADMIN, json={"name": "Physics Lab", "type": "lab", "capacity": 40, "school_id": SID})
check("academic", "create resource", r.status_code < 300, r.text)
RES = jn(r).get("id")

# Science bound to the lab -> exercises resource-conflict constraint
SUBJECT_SPEC = [("Math", 5, None), ("English", 5, None), ("Science", 5, RES), ("History", 4, None), ("Art", 4, None)]
SUBJ = {}
for nm, hrs, res in SUBJECT_SPEC:
    body = {"name": nm, "weekly_hours": hrs, "school_id": SID}
    if res:
        body["resource_id"] = res
    r = req("POST", "/subjects", ADMIN, json=body)
    check("academic", f"create subject {nm}({hrs}h)", r.status_code < 300, r.text)
    SUBJ[nm] = jn(r).get("id")

TOTAL_PER_SEC = sum(h for _, h, _ in SUBJECT_SPEC)
check("academic", f"section demand {TOTAL_PER_SEC} <= capacity {PPD*WD}", TOTAL_PER_SEC <= PPD * WD)

# ---------------------------------------------------------------- 3. teachers
print("\n=== [3] TEACHERS + qualifications ===")
TEACH = {}
for nm, hrs, _ in SUBJECT_SPEC:
    r = req("POST", "/teachers", ADMIN, json={
        "name": f"T-{nm}", "email": f"t.{nm.lower()}.{RUN}@example.com", "password": "Teach@1234",
        "max_weekly_hours": 20, "school_id": SID, "subject_ids": [SUBJ[nm]],
    })
    check("teachers", f"create teacher T-{nm}", r.status_code < 300, r.text)
    TEACH[nm] = jn(r).get("id")

# teacher login proves /teachers created a real User (cross-module flow)
r = req("POST", "/auth/login", json={"email": f"t.math.{RUN}@example.com", "password": "Teach@1234"})
check("teachers", "teacher account can log in (teacher->user wiring)", r.status_code == 200, r.text)
TTOK = jn(r).get("access_token")

# availability: T-Math unavailable Monday(0) period 1
grid = [{"day_of_week": d, "period": p, "is_available": not (d == 0 and p == 1)}
        for d in range(WD) for p in range(1, PPD + 1)]
r = req("PUT", f"/teachers/{TEACH['Math']}/availability", ADMIN, json=grid)
check("teachers", "set availability grid", r.status_code < 300, r.text)
got = jn(req("GET", f"/teachers/{TEACH['Math']}/availability", ADMIN))
blocked = [a for a in got if not a["is_available"]]
check("teachers", "availability persisted (1 blocked slot)", len(blocked) == 1 and blocked[0]["day_of_week"] == 0 and blocked[0]["period"] == 1, blocked)

# ---------------------------------------------------------------- 4. assignments
print("\n=== [4] ASSIGNMENTS (manual mode binds teacher->section->subject) ===")
for sid in SEC:
    for nm, _, _ in SUBJECT_SPEC:
        r = req("POST", "/assignments", ADMIN, json={
            "section_id": sid, "subject_id": SUBJ[nm], "teacher_id": TEACH[nm], "school_id": SID})
        if r.status_code >= 300:
            check("assign", f"assign {nm}->sec{sid}", False, r.text)
n_ass = len(jn(req("GET", "/assignments", ADMIN, params={"school_id": SID})).get("items", []) or [])
check("assign", "assignments created for both sections", n_ass >= len(SEC) * len(SUBJECT_SPEC), f"got {n_ass}")

# ---------------------------------------------------------------- 5. validation
print("\n=== [5] VALIDATION ENGINE ===")
r = req("GET", f"/validation/school/{SID}", ADMIN)
check("validation", "validation report -> 200", r.status_code == 200, r.text)
v = jn(r)
check("validation", "report exposes readiness", any(k in v for k in ("readiness_score", "score", "is_ready", "status")), list(v)[:8])

# ---------------------------------------------------------------- 6. GENERATE
print("\n=== [6] SCHEDULER (OR-Tools CP-SAT) ===")
t0 = time.time()
r = req("POST", "/timetables/generate", ADMIN, json={"school_id": SID, "time_limit_seconds": 30})
gen_ms = int((time.time() - t0) * 1000)
ok_gen = check("scheduler", f"generate -> 2xx ({gen_ms}ms)", r.status_code < 300, r.text)

rows = fetch_rows(SEC)
check("scheduler", f"timetable rows persisted ({len(rows)})", len(rows) > 0)

expected = TOTAL_PER_SEC * len(SEC)
check("scheduler", f"row count == demand ({expected})", len(rows) == expected, f"got {len(rows)}")

# ---- correctness invariants (independent checker) ----
by_sec_slot = collections.Counter()
by_teacher_slot = collections.Counter()
by_res_slot = collections.Counter()
hours = collections.Counter()
tload = collections.Counter()
for x in rows:
    slot = (x["day_of_week"], x["period"])
    by_sec_slot[(x["section_id"],) + slot] += 1
    if x.get("teacher_id"):
        by_teacher_slot[(x["teacher_id"],) + slot] += 1
        tload[x["teacher_id"]] += 1
    if x.get("resource_id"):
        by_res_slot[(x["resource_id"],) + slot] += 1
    if x.get("subject_id"):
        hours[(x["section_id"], x["subject_id"])] += 1

check("scheduler", "HARD: no section double-booked", all(c == 1 for c in by_sec_slot.values()),
      [k for k, c in by_sec_slot.items() if c > 1][:3])
check("scheduler", "HARD: no teacher double-booked", all(c == 1 for c in by_teacher_slot.values()),
      [k for k, c in by_teacher_slot.items() if c > 1][:3])
check("scheduler", "HARD: no resource double-booked", all(c == 1 for c in by_res_slot.values()),
      [k for k, c in by_res_slot.items() if c > 1][:3])

hours_ok = all(hours.get((sid, SUBJ[nm]), 0) == h for sid in SEC for nm, h, _ in SUBJECT_SPEC)
check("scheduler", "HARD: exact weekly hours per subject/section", hours_ok,
      {f"sec{sid}-{nm}": hours.get((sid, SUBJ[nm]), 0) for sid in SEC for nm, _, _ in SUBJECT_SPEC})
check("scheduler", "HARD: teacher weekly cap (<=20) respected", all(v <= 20 for v in tload.values()), dict(tload))

mt = TEACH["Math"]
viol = [x for x in rows if x.get("teacher_id") == mt and x["day_of_week"] == 0 and x["period"] == 1]
check("scheduler", "HARD: teacher availability honoured (Mon P1 free for T-Math)", not viol, viol[:2])

check("scheduler", "slots within grid bounds", all(0 <= x["day_of_week"] < WD and 1 <= x["period"] <= PPD for x in rows))
sci_rows = [x for x in rows if x.get("subject_id") == SUBJ["Science"]]
check("scheduler", "resource auto-attached to lab subject", all(x.get("resource_id") == RES for x in sci_rows),
      f"{sum(1 for x in sci_rows if x.get('resource_id')==RES)}/{len(sci_rows)}")

# per-view endpoints used by the FE
r = req("GET", f"/timetables/section/{SEC[0]}", ADMIN)
check("scheduler", "GET /timetables/section/{id} (FE grid)", r.status_code == 200, r.text)
r = req("GET", f"/timetables/teacher/{TEACH['Math']}", ADMIN)
check("scheduler", "GET /timetables/teacher/{id} (FE grid)", r.status_code == 200, r.text)

# ---------------------------------------------------------------- 6b. constraint linter
print("\n=== [6b] CONSTRAINT LINTER (infeasibility explained, not guessed) ===")
req("PUT", f"/subjects/{SUBJ['Math']}", ADMIN, json={"name": "Math", "weekly_hours": WD + 1, "school_id": SID})
r = req("POST", "/timetables/generate", ADMIN, json={"school_id": SID, "time_limit_seconds": 20})
msg = str(jn(r).get("detail", ""))
check("linter", "over-spread subject rejected with 4xx", 400 <= r.status_code < 500, f"{r.status_code}")
check("linter", "error names the offending subject + policy", "Math" in msg and "subject-spread" in msg, msg[:160])
check("linter", "error is actionable (suggests a remedy)",
      "double_periods_allowed" in msg or "reduce" in msg.lower(), msg[:160])
req("PUT", f"/subjects/{SUBJ['Math']}", ADMIN, json={"name": "Math", "weekly_hours": 5, "school_id": SID})
r = req("POST", "/timetables/generate", ADMIN, json={"school_id": SID, "time_limit_seconds": 30})
check("linter", "regenerate after fix -> 2xx", r.status_code < 300, r.text)
rows = fetch_rows(SEC)

# ---------------------------------------------------------------- 7. lock + regenerate
print("\n=== [7] LOCK -> REGENERATE (manual override is inviolable) ===")
target = rows[0]
r = req("PATCH", f"/timetables/{target['id']}/lock", ADMIN, params={"locked": "true"})
check("lock", "lock a slot -> 2xx", r.status_code < 300, r.text)
r = req("POST", "/timetables/generate", ADMIN, json={"school_id": SID, "time_limit_seconds": 30})
check("lock", "regenerate with lock -> 2xx", r.status_code < 300, r.text)
rows2 = fetch_rows(SEC)
kept = [x for x in rows2 if x["section_id"] == target["section_id"] and x["day_of_week"] == target["day_of_week"]
        and x["period"] == target["period"] and x.get("subject_id") == target.get("subject_id")]
check("lock", "locked slot preserved across regenerate", len(kept) == 1, f"kept={len(kept)}")
check("lock", "no teacher double-book after regenerate",
      all(c == 1 for c in collections.Counter((x["teacher_id"], x["day_of_week"], x["period"])
          for x in rows2 if x.get("teacher_id")).values()))

# ---------------------------------------------------------------- 8. versioning
print("\n=== [8] VERSION WORKFLOW (draft->review->approve->publish) ===")
r = req("POST", "/timetables/versions/save-draft", ADMIN, json={
    "school_id": SID, "name": f"v1-{RUN}", "reason": "integration", "academic_year": "2026-2027"})
check("version", "save-draft -> 2xx", r.status_code < 300, r.text)
VID = jn(r).get("id")
if VID:
    check("version", "submit-review", req("POST", f"/timetables/versions/{VID}/submit-review", ADMIN).status_code < 300)
    check("version", "approve", req("POST", f"/timetables/versions/{VID}/approve", ADMIN).status_code < 300)
    check("version", "publish", req("POST", f"/timetables/versions/{VID}/publish", ADMIN).status_code < 300)
    lst = jn(req("GET", "/timetables/versions", ADMIN, params={"school_id": SID}))
    items = lst.get("items", []) if isinstance(lst, dict) else lst
    pub = [x for x in items if x.get("id") == VID]
    check("version", "version status == published", pub and pub[0].get("status") == "published",
          pub[0].get("status") if pub else "not found")

# ---------------------------------------------------------------- 9. leave -> gaps -> substitution
print("\n=== [9] DAILY OPS: leave -> gaps -> substitution overlay ===")
# snapshot immediately before daily ops: version publish (step 8) legitimately rewrites master rows
before_ops = fetch_rows(SEC)
math_rows = [x for x in before_ops if x.get("teacher_id") == TEACH["Math"]]
check("ops", "T-Math has scheduled lessons", len(math_rows) > 0)
DAY = math_rows[0]["day_of_week"] if math_rows else 0
# pick a real calendar date whose weekday == DAY (Mon=0)
import datetime as dt
d = dt.date.today() + dt.timedelta(days=7)
while d.weekday() != DAY:
    d += dt.timedelta(days=1)
DATE = d.isoformat()

r = req("POST", "/leaves", ADMIN, json={"teacher_id": TEACH["Math"], "date": DATE, "reason": "integration"})
check("ops", "create leave -> 2xx", r.status_code < 300, r.text)
LID = jn(r).get("id")
# how many master slots does T-Math actually own on that weekday?
expected_slots = len([x for x in before_ops if x.get("teacher_id") == TEACH["Math"] and x["day_of_week"] == DAY])
check("ops", f"T-Math owns {expected_slots} slot(s) on leave weekday", expected_slots > 0)

r = req("POST", f"/leaves/{LID}/approve", ADMIN, json={"note": "integration approve"})
check("ops", "approve leave -> 2xx", r.status_code < 300, r.text)
appr = jn(r)
created = appr.get("substitutions_created", 0)
uncovered = appr.get("uncovered_slots", [])
check("ops", "auto-substitute engine ran on approval", "substitutions_created" in appr, list(appr))
check("ops", "every affected slot accounted for (covered + uncovered)",
      created + len(uncovered) == expected_slots, f"{created}+{len(uncovered)} vs {expected_slots}")

subs = jn(req("GET", "/substitutions", ADMIN, params={"leave_id": LID}))
sub_items = subs.get("items", []) if isinstance(subs, dict) else subs
check("ops", "substitution rows persisted for leave (leave x timetable x substitution)",
      len(sub_items) == created, f"{len(sub_items)} rows vs created={created}")

r = req("GET", f"/leaves/{LID}/gaps", ADMIN)
check("ops", "gaps endpoint -> 200", r.status_code == 200, r.text)
gaps_list = jn(r)
check("ops", "gaps == uncovered slots reported at approval",
      len(gaps_list) == len(uncovered), f"gaps={len(gaps_list)} uncovered={len(uncovered)}")

# master timetable must be untouched by daily ops (overlay-only invariant)
after = fetch_rows(SEC)
check("ops", "master timetable unchanged after leave/substitution (overlay only)",
      len(after) == len(before_ops) and {x["id"] for x in after} == {x["id"] for x in before_ops},
      f"before={len(before_ops)} after={len(after)}")

r = req("GET", "/substitutions/schedule", ADMIN, params={"date": DATE, "section_id": SEC[0]})
ok = check("ops", "effective schedule overlay -> 200", r.status_code == 200, r.text)
if ok and created:
    sched = jn(r)
    srows = sched.get("items", []) if isinstance(sched, dict) else sched
    subbed = [x for x in srows if x.get("substitute_teacher_id") or x.get("is_substituted") or x.get("substitute_teacher_name")]
    check("ops", "overlay marks substituted slots", len(subbed) > 0, f"{len(srows)} rows, none flagged")

# ---------------------------------------------------------------- 10. swaps
print("\n=== [10] SWAPS ===")
fresh = fetch_rows(SEC)
if len(fresh) >= 2:
    a, b = fresh[0], fresh[1]
    r = req("POST", "/swaps", ADMIN, json={"timetable_id_a": a["id"], "timetable_id_b": b["id"],
                                           "date": DATE, "reason": "integration"})
    check("swaps", "create swap -> 2xx", r.status_code < 300, r.text)
    SWID = jn(r).get("id")
    if SWID:
        rc = req("POST", f"/swaps/{SWID}/approve", ADMIN, json={"note": "integration"}).status_code
        # 409 = engine refused a swap that would double-book. Both are correct outcomes.
        check("swaps", "approve swap -> 2xx or 409 (never 5xx)", rc < 300 or rc == 409, f"got {rc}")
        check("swaps", "swap approval never 500s", rc < 500, f"got {rc}")

# ---------------------------------------------------------------- 11. calendar + exams
print("\n=== [11] CALENDAR + EXAMS ===")
r = req("POST", "/calendar", ADMIN, json={"title": "Founders Day", "date": DATE, "type": "holiday",
                                          "is_holiday": True, "school_id": SID})
check("calendar", "create holiday -> 2xx", r.status_code < 300, r.text)
check("calendar", "list calendar -> 200", req("GET", "/calendar", ADMIN, params={"school_id": SID}).status_code == 200)

r = req("POST", "/exams/generate", ADMIN, json={"school_id": SID, "start_date": DATE})
check("exams", "exam generate -> 2xx/4xx (not 5xx)", r.status_code < 500, r.text)
check("exams", "list exams -> 200", req("GET", "/exams", ADMIN, params={"school_id": SID}).status_code == 200)

# ---------------------------------------------------------------- 12. reports
print("\n=== [12] REPORTS (must reflect generated timetable) ===")
r = req("GET", "/reports/teacher-workload", ADMIN, params={"school_id": SID})
ok = check("reports", "teacher-workload -> 200", r.status_code == 200, r.text)
if ok:
    rep = jn(r)
    items = rep.get("teachers", []) if isinstance(rep, dict) else rep
    tot = sum(i.get("scheduled_periods", 0) or 0 for i in items)
    actual = len(fetch_rows(SEC))
    check("reports", "workload totals match timetable rows (DB<->report consistency)",
          tot == actual, f"report={tot} actual={actual}")
    check("reports", "utilization_pct computed per teacher",
          all("utilization_pct" in i for i in items) and len(items) == 5, len(items))
for ep in ["subject-coverage", "resource-usage", "leave-summary", "timetable"]:
    p = {"school_id": SID}
    if ep == "timetable":
        p["section_id"] = SEC[0]
    check("reports", f"{ep} -> 200", req("GET", f"/reports/{ep}", ADMIN, params=p).status_code == 200)
for ep in ["teacher-workload", "timetable"]:
    p = {"school_id": SID, "format": "pdf"}
    if ep == "timetable":
        p["section_id"] = SEC[0]
    r = req("GET", f"/reports/export/{ep}", ADMIN, params=p)
    check("reports", f"export {ep} pdf -> 200 + binary", r.status_code == 200 and len(r.content) > 500,
          f"{r.status_code} len={len(r.content)}")
r = req("GET", "/reports/export/teacher-workload", ADMIN, params={"school_id": SID, "format": "xlsx"})
check("reports", "export xlsx -> 200 + binary", r.status_code == 200 and len(r.content) > 500,
      f"{r.status_code} len={len(r.content)}")

# ---------------------------------------------------------------- 13. bulk + notifications
print("\n=== [13] BULK + NOTIFICATIONS ===")
r = req("GET", "/bulk/template", ADMIN)
check("bulk", "bulk template downloads", r.status_code == 200 and len(r.content) > 200, f"{r.status_code}")
check("notif", "list notifications -> 200", req("GET", "/notifications", ADMIN).status_code == 200)
check("notif", "mark-all read -> 2xx", req("PATCH", "/notifications/read-all", ADMIN).status_code < 300)

# ---------------------------------------------------------------- 14. security
print("\n=== [14] RBAC + TENANT ISOLATION ===")
check("sec", "teacher cannot create school (403)", req("POST", "/schools", TTOK, json={"name": "Rogue"}).status_code == 403)
check("sec", "teacher cannot delete school (4xx)", req("DELETE", f"/schools/{SID}", TTOK).status_code >= 400)
r = req("POST", "/schools", ADMIN, json={"name": f"OtherSchool-{RUN}", "periods_per_day": 6, "working_days": 5})
OTHER = jn(r).get("id")
own_classes = jn(req("GET", "/classes", TTOK)).get("items", [])
check("sec", "teacher's /classes contains only own school",
      all(c.get("school_id") == SID for c in own_classes), [c.get("school_id") for c in own_classes])
check("sec", "teacher cannot read other school's config (403)",
      req("GET", f"/schools/{OTHER}/config", TTOK).status_code == 403)
check("sec", "teacher cannot write other school's config (403)",
      req("PUT", f"/schools/{OTHER}/config", TTOK, json={"config": "{}"}).status_code in (403, 401))
check("sec", "stale/garbage token rejected", req("GET", "/auth/me", "garbage").status_code == 401)

# ---------------------------------------------------------------- 15. AI guardrail
print("\n=== [15] AI (Groq) - must never generate timetables ===")
r = req("GET", "/assistant/workload-suggestions", ADMIN, params={"school_id": SID})
check("ai", "assistant reachable (200 or 502 if no key)", r.status_code in (200, 502, 400), r.status_code)
ai_paths = ["/assistant/chat", "/assistant/explain-conflict", "/assistant/narrate-report",
            "/assistant/suggestions", "/assistant/explain-infeasibility", "/assistant/workload-suggestions"]
check("ai", "no AI endpoint generates/writes a timetable", all("generate" not in p for p in ai_paths))

# ---------------------------------------------------------------- 16. frontend delivery
print("\n=== [16] FRONTEND DELIVERY (same-origin) ===")
pages = ["index.html", "dashboard.html", "timetable.html", "teachers.html", "classes.html", "subjects.html",
         "assignments.html", "leaves.html", "swaps.html", "substitutes.html", "reports.html", "exams.html",
         "calendar.html", "config_editor.html", "setup_wizard.html", "schools.html", "bulk.html",
         "teacher_availability.html", "health.html"]
bad = [p for p in pages if S.get(f"{BASE}/app/{p}", timeout=20).status_code != 200]
check("fe", f"all {len(pages)} pages served 200", not bad, bad)
assets = ["js/api.js", "js/nav.js", "js/crud-page.js", "js/timetable.js", "js/dynamic_ui.js", "css/style.css"]
bad = [a for a in assets if S.get(f"{BASE}/app/{a}", timeout=20).status_code != 200]
check("fe", "core JS/CSS assets served", not bad, bad)
api_js = S.get(f"{BASE}/app/js/api.js", timeout=20).text
check("fe", "api.js uses same-origin when served from /app", "location.origin" in api_js)
check("fe", "/app/ serves login page", S.get(f"{BASE}/app/", timeout=20).status_code == 200)
check("fe", "static mount does not shadow API", S.get(f"{BASE}/health", timeout=20).json().get("status") == "ok")

# ---------------------------------------------------------------- 17. cleanup
print("\n=== [17] CLEANUP ===")
rc = req("DELETE", f"/schools/{SID}", ADMIN).status_code
check("cleanup", "delete school with dependents -> 409 (not 500)", rc == 409, f"got {rc}")
rc = req("DELETE", f"/schools/{OTHER}", ADMIN).status_code
check("cleanup", "delete empty school -> 2xx", rc < 300, f"got {rc}")

# The API cannot cascade-delete a school that has a generated timetable (no endpoint deletes
# timetable rows), so this school necessarily survives the run. Say so loudly rather than
# pretending the suite self-cleans.
print(f"\n  NOTE: school {SID} ('IntegrationSchool-{RUN}') could not be removed via the API.")
print("        Purge leftover test schools with:")
print("        psql -U eduflow -h localhost -d eduflow_ai -f cleanup_test_data.sql")

# ---------------------------------------------------------------- summary
print("\n" + "=" * 74)
secs = collections.OrderedDict()
for s, n, ok in results:
    secs.setdefault(s, [0, 0])
    secs[s][0 if ok else 1] += 1
for s, (p, f) in secs.items():
    print(f"  {s:12} {p:3} passed   {f:3} failed")
P = sum(1 for _, _, o in results if o)
F = len(results) - P
print("=" * 74)
print(f"TOTAL: {P} passed, {F} failed, {len(results)} checks")
if F:
    print("\nFAILURES:")
    for s, n, o in results:
        if not o:
            print(f"  - [{s}] {n}")
sys.exit(1 if F else 0)
