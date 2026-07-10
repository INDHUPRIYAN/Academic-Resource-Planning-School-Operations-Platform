"""
Apply teacher availability constraints for Avinashi GGHSS, then regenerate the
master timetable. Imported by Avinashi_GGHSS_seed.py (which applies these grids
before its single generate); also runnable standalone to re-apply + regenerate.

Two ways of expressing availability, one storage model
-----------------------------------------------------
The database stores an explicit (day, period) -> is_available grid per teacher,
and the scheduler treats it as a HARD constraint. Both modes below are just
different ways of writing the same grid, so no scheduler change is needed:

  BLOCKED  ("NOT AVAILABLE hours")  listed periods are unavailable, rest available.
                                    Used by teachers who hold 11th/12th classes then.

  ALLOWED  ("ONLY AVAILABLE hours") listed periods are the ONLY available ones,
                                    every other period is unavailable.

Writing the full 40-cell grid for every teacher makes the intent explicit and
removes any reliance on "absent row means available".

Usage:  python seed_availability.py     (server must be running)
"""
import os
import sys
import time
import collections

import requests

BASE = os.environ.get("EDUFLOW_BASE_URL", "http://127.0.0.1:8010").rstrip("/")
ADMIN_EMAIL, ADMIN_PASSWORD = "admin@school.edu", "Admin@123"
PPD, WD = 8, 5
DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]

BLOCKED = {
    # Periods occupied by 11th & 12th Standard classes.
    "Kavitha": {0: [7], 1: [3], 2: [6], 3: [2, 8], 4: [3, 5]},
}

ALLOWED = {
    # The ONLY periods in which 6th-10th classes may be scheduled.
    "Hellen":       {0: [5, 6, 8],          1: [1, 2, 5],       2: [1, 2, 4, 6, 7, 8], 3: [3, 6, 7, 8],       4: [3]},
    "Jaya Pratha":  {0: [5, 7, 8],          1: [1, 3, 6],       2: [6, 7, 8],       3: [2, 3, 4, 5, 8],       4: [1, 4, 5]},
    "Santhiya":     {0: [3, 4, 5, 6, 8],    1: [1, 2, 7, 8],    2: [3, 4, 5, 6, 8], 3: [1, 2, 3, 4, 7, 8],    4: [1, 2, 3, 4, 6]},
    "Subbu":        {0: [3, 4, 6, 7, 8],    1: [4, 5, 6, 7, 8], 2: [1, 3, 4],       3: [1, 2, 4, 5, 6, 7],    4: [1, 2, 4, 6]},
    "Jaya Chitra":  {0: [1, 2, 4, 5, 7, 8], 1: [1, 3, 6, 8],    2: [3, 4, 5, 7, 8], 3: [3, 4, 5, 6, 8],       4: [1, 4, 5, 6]},
}

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


def grid_from_blocked(spec):
    return [{"day_of_week": d, "period": p, "is_available": p not in spec.get(d, [])}
            for d in range(WD) for p in range(1, PPD + 1)]


def grid_from_allowed(spec):
    return [{"day_of_week": d, "period": p, "is_available": p in spec.get(d, [])}
            for d in range(WD) for p in range(1, PPD + 1)]


def main():
    global TOK
    try:
        requests.get(f"{BASE}/health", timeout=5)
    except Exception:
        sys.exit(f"Server not reachable at {BASE}")

    TOK = api("POST", "/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})["access_token"]
    teachers = api("GET", "/teachers", params={"limit": 100})["items"]
    by_name = {t["name"]: t for t in teachers}
    school_id = teachers[0]["school_id"]

    missing = [n for n in {**BLOCKED, **ALLOWED} if n not in by_name]
    if missing:
        sys.exit(f"Teachers not found: {missing}. Run seed_demo_school.py first.")

    print("== Applying availability ==")
    for name, spec in BLOCKED.items():
        grid = grid_from_blocked(spec)
        api("PUT", f"/teachers/{by_name[name]['id']}/availability", json=grid)
        n_blocked = sum(1 for c in grid if not c["is_available"])
        print(f"  {name:14} BLOCKED mode -> {40 - n_blocked} available, {n_blocked} blocked")

    for name, spec in ALLOWED.items():
        grid = grid_from_allowed(spec)
        api("PUT", f"/teachers/{by_name[name]['id']}/availability", json=grid)
        n_ok = sum(1 for c in grid if c["is_available"])
        print(f"  {name:14} ALLOWED mode -> {n_ok} available, {40 - n_ok} unavailable")

    print("\n== Read back from DB (mode-independent grid) ==")
    stored = {}
    for name in {**BLOCKED, **ALLOWED}:
        rows = api("GET", f"/teachers/{by_name[name]['id']}/availability")
        avail = {(r["day_of_week"], r["period"]) for r in rows if r["is_available"]}
        stored[name] = avail
        print(f"  {name:14} {len(rows):2} cells stored, {len(avail):2} available")

    # storage must reproduce the source spec exactly
    for name, spec in ALLOWED.items():
        want = {(d, p) for d in range(WD) for p in spec.get(d, [])}
        assert stored[name] == want, f"{name}: stored != spec"
    for name, spec in BLOCKED.items():
        want = {(d, p) for d in range(WD) for p in range(1, PPD + 1) if p not in spec.get(d, [])}
        assert stored[name] == want, f"{name}: stored != spec"
    print("  all grids round-trip exactly\n")

    print("== Regenerating timetable under hard availability constraints ==")
    t0 = time.time()
    api("POST", "/timetables/generate", json={"school_id": school_id, "time_limit_seconds": 300})
    print(f"  solved in {time.time() - t0:.1f}s\n")

    secs = api("GET", "/sections", params={"limit": 200})["items"]
    rows = []
    for s in secs:
        rows += api("GET", "/timetables", params={"section_id": s["id"], "limit": 200})["items"]
    lessons = [r for r in rows if r.get("subject_id")]

    print("== Verifying availability was honoured ==")
    ok = True

    def chk(name, cond, detail=""):
        nonlocal ok
        ok = ok and cond
        print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" -> {detail}" if not cond and detail else ""))

    for name, avail in stored.items():
        placed = {(r["day_of_week"], r["period"]) for r in lessons if r["teacher_name"] == name}
        outside = sorted(placed - avail)
        chk(f"{name} taught only in available periods",
            not outside, [f"{DAYS[d]} P{p}" for d, p in outside[:4]])

    n = len(lessons)
    chk("all 532 lessons still scheduled", n == 532, n)
    tch = collections.Counter((r["teacher_id"], r["day_of_week"], r["period"]) for r in lessons)
    chk("no teacher clash", all(v == 1 for v in tch.values()))
    sec = collections.Counter((r["section_id"], r["day_of_week"], r["period"]) for r in rows)
    chk("no class clash", all(v == 1 for v in sec.values()))
    ptd = [r for r in rows if r.get("activity_id")]
    chk("fixed PTD intact (Fri P7/P8)",
        len(ptd) == 28 and all(r["day_of_week"] == 4 and r["period"] in (7, 8) for r in ptd))

    load = collections.Counter(r["teacher_name"] for r in lessons)
    for name in stored:
        avail_ct = len(stored[name])
        chk(f"{name} load {load[name]} <= {avail_ct} available slots", load[name] <= avail_ct)

    print(f"\nView: {BASE}/app/timetable.html")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
