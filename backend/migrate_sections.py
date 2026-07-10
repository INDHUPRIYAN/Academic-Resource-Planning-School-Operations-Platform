"""Add `medium` and `class_teacher_id` to the sections table.

Base.metadata.create_all() only creates missing tables, never missing columns, so
existing databases need this. Safe to run repeatedly — it inspects before altering
and leaves existing rows untouched (both columns are nullable).

Usage:  python migrate_sections.py
"""
from sqlalchemy import inspect, text

from app.database import engine

DDL = {
    "medium": {
        "postgresql": "ALTER TABLE sections ADD COLUMN medium VARCHAR(50)",
        "sqlite": "ALTER TABLE sections ADD COLUMN medium VARCHAR(50)",
    },
    "class_teacher_id": {
        "postgresql": (
            "ALTER TABLE sections ADD COLUMN class_teacher_id INTEGER "
            "REFERENCES teachers(id)"
        ),
        # SQLite cannot add a column with an inline FK reference to an existing table.
        "sqlite": "ALTER TABLE sections ADD COLUMN class_teacher_id INTEGER",
    },
}


def main() -> None:
    dialect = engine.dialect.name
    inspector = inspect(engine)

    if "sections" not in inspector.get_table_names():
        print("No `sections` table yet — run seed_admin.py first. Nothing to do.")
        return

    existing = {c["name"] for c in inspector.get_columns("sections")}
    print(f"dialect={dialect}  existing sections columns: {sorted(existing)}")

    added = []
    with engine.begin() as conn:
        for column, per_dialect in DDL.items():
            if column in existing:
                print(f"  - {column}: already present, skipping")
                continue
            stmt = per_dialect.get(dialect)
            if not stmt:
                raise RuntimeError(f"No migration defined for dialect {dialect!r}")
            conn.execute(text(stmt))
            added.append(column)
            print(f"  + {column}: added")

    if added:
        after = {c["name"] for c in inspect(engine).get_columns("sections")}
        missing = [c for c in DDL if c not in after]
        if missing:
            raise RuntimeError(f"Migration reported success but columns missing: {missing}")
        print(f"\nMigration complete. Added: {', '.join(added)}")
    else:
        print("\nNothing to migrate — schema already up to date.")


if __name__ == "__main__":
    main()
