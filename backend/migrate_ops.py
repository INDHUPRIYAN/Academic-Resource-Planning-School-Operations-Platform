"""Migration: Daily Operations module (Phase 1).

Idempotent - safe to run repeatedly, and safe on a database that already holds
live timetable data. It performs only additive changes:

  1. roleenum        += 'principal', 'vice_principal'
     (Postgres cannot ALTER TYPE inside a transaction, so this runs autocommit.)
  2. on_duty table   created (via metadata.create_all, which also creates the
     ondutystatus enum). create_all never touches existing tables.
  3. substitutions   leave_id -> NULLABLE, and a new on_duty_id FK, so a cover can
     be raised by either an approved leave OR an approved on-duty.

Usage:  DATABASE_URL=... python migrate_ops.py
"""
import os
import sys

from sqlalchemy import create_engine, text

from app.database import Base, engine
from app import models  # noqa: F401  (registers all tables on Base.metadata)


def main():
    url = os.environ.get("DATABASE_URL")
    print(f"== Migrating {'(DATABASE_URL set)' if url else '(default engine)'} ==")

    # ---- 1. role enum ------------------------------------------------------
    # ALTER TYPE ... ADD VALUE cannot run inside a transaction block.
    ac = engine.execution_options(isolation_level="AUTOCOMMIT")
    with ac.connect() as c:
        existing = {r[0] for r in c.execute(text(
            "select e.enumlabel from pg_type t join pg_enum e on e.enumtypid=t.oid "
            "where t.typname='roleenum'"))}
        for value in ("principal", "vice_principal"):
            if value in existing:
                print(f"  roleenum: '{value}' already present - skipped")
            else:
                c.execute(text(f"ALTER TYPE roleenum ADD VALUE '{value}'"))
                print(f"  roleenum: added '{value}'")

    # ---- 2. new tables (on_duty) ------------------------------------------
    before = engine.dialect.has_table(engine.connect(), "on_duty")
    Base.metadata.create_all(bind=engine)
    after = engine.dialect.has_table(engine.connect(), "on_duty")
    print(f"  on_duty table: {'already existed' if before else ('created' if after else 'FAILED')}")

    # ---- 3. substitutions: allow on-duty-driven cover ----------------------
    with engine.begin() as c:
        nullable = c.execute(text(
            "select is_nullable from information_schema.columns "
            "where table_name='substitutions' and column_name='leave_id'")).scalar()
        if nullable == "NO":
            c.execute(text("ALTER TABLE substitutions ALTER COLUMN leave_id DROP NOT NULL"))
            print("  substitutions.leave_id -> nullable")
        else:
            print("  substitutions.leave_id already nullable - skipped")

        has_col = c.execute(text(
            "select 1 from information_schema.columns "
            "where table_name='substitutions' and column_name='on_duty_id'")).scalar()
        if not has_col:
            c.execute(text(
                "ALTER TABLE substitutions ADD COLUMN on_duty_id INTEGER "
                "REFERENCES on_duty(id)"))
            print("  substitutions.on_duty_id -> added")
        else:
            print("  substitutions.on_duty_id already present - skipped")

        # ---- 4. ranked queue + cross-day swap columns -----------------------
        add_cols = [
            ("substitutions", "rank", "INTEGER"),
            ("substitutions", "score", "INTEGER"),
            ("substitutions", "decline_reason", "TEXT"),
            ("swaps", "date_b", "DATE"),
            ("swaps", "target_accepted", "BOOLEAN"),
            ("swaps", "target_note", "TEXT"),
            ("swaps", "target_reviewed_at", "TIMESTAMP"),
        ]
        for table, col, coltype in add_cols:
            exists = c.execute(text(
                "select 1 from information_schema.columns "
                f"where table_name='{table}' and column_name='{col}'")).scalar()
            if exists:
                print(f"  {table}.{col} already present - skipped")
            else:
                c.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {coltype}"))
                print(f"  {table}.{col} -> added")

    print("\n== Migration complete ==")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("MIGRATION FAILED:", e)
        sys.exit(1)
