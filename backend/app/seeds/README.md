# Institution seeds

Each seed here fully initializes **one institution** — its structure, staff,
subjects, rules, availability and (for schools) a generated timetable. The
backend runs a **single, configuration-driven scheduling engine**: it reads
every constraint from the institution's saved configuration and does not branch
on "school" vs "college". Adding a new institution is therefore configuration,
not code.

## Two ways to configure an institution

**Method 1 — Manual (UI).** A school/college admin creates the institution and
adds classes, sections, teachers, subjects, activities, resources, availability
and scheduling policies through the app (`setup_wizard.html`, `config_editor.html`,
and the per-entity pages). No developer needed.

**Method 2 — Python seed file (this folder).** A developer initializes a complete
institution by running one file. Intended for development, testing and demos.
Both methods write the same data model, so a seeded institution and a
UI-configured one are indistinguishable to the engine.

## Files

| File | Institution | Status |
|------|-------------|--------|
| `Avinashi_GGHSS_seed.py` | Avinashi GGHSS (school) | Complete — all data + timetable |
| `avinashi_availability.py` | (teacher availability grids for the above) | Complete |
| `Sri_Shakthi_seed.py` | Sri Shakthi (college) | Placeholder scaffold — runs error-free, ready to populate |

## Running

The server must be running (seeds build over the REST API), with `DATABASE_URL`
and `EDUFLOW_BASE_URL` pointing at the target environment:

```bash
python -m uvicorn app.main:app --port 8010          # from backend/
python -m app.seeds.Avinashi_GGHSS_seed             # school: DESTRUCTIVE (wipes all tables first)
python -m app.seeds.Sri_Shakthi_seed                # college: safe; prints a plan while it is a placeholder
```

Back-compat: `python seed_demo_school.py` and `python seed_availability.py`
still work — they are thin shims delegating to the files above.

## College mapping

`Sri_Shakthi_seed.py`'s docstring documents how college concepts (department,
program, semester, section, faculty, course, lab, elective, shared faculty,
credit hours, timetable rules) map onto the existing platform primitives, so the
same engine generates college timetables once real data is supplied.
