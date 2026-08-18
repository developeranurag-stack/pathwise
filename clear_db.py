"""Clear the database by dropping the entire 'public' schema, then initialize it.

This gives a completely fresh DB with schema + seed data (careers + scholarships).

After running this the DB is ready; you can start the server or run create_demo_user.py.

Usage:
  python clear_db.py

WARNING: DESTRUCTIVE. Destroys ALL data in the connected database.
"""
import sys

import db as dbmod


def _apply_gov_job_columns(raw_conn):
    """Ensure MCP search columns exist even if schema.sql is an older copy."""
    extras = [
        ("commission", "TEXT"),
        ("state", "TEXT"),
        ("exam_name", "TEXT"),
        ("exam_kind", "TEXT"),
        ("search_document", "TEXT"),
        ("translations", "JSONB"),
        ("age_relaxation_details", "JSONB"),
        ("nationality", "TEXT"),
        ("syllabus", "JSONB"),
        ("exam_date", "TEXT"),
        ("advertisement_number", "TEXT"),
        ("application_fee", "TEXT"),
    ]
    with raw_conn.cursor() as cur:
        for column, ddl in extras:
            cur.execute(
                f"ALTER TABLE gov_job_notifications ADD COLUMN IF NOT EXISTS {column} {ddl}"
            )
        cur.execute("ALTER TABLE gov_job_posts ADD COLUMN IF NOT EXISTS translations JSONB")
    raw_conn.commit()


def init_schema_and_seeds():
    """Rebuild schema + seed without importing the Flask app.

    `import main` used to do this as a side effect of module import. That loads
    the whole web app, prints nothing, and only commits after all ~890 careers
    are inserted — so a Ctrl-C / timeout leaves an empty schema.
    """
    print("Applying schema.sql ...", flush=True)
    created = dbmod.init_db()
    print(f"  schema {'created' if created else 'already present'}", flush=True)

    raw = dbmod.connect()
    try:
        _apply_gov_job_columns(raw)
    finally:
        raw.close()

    from seed_data import CAREERS, SCHOLARSHIPS, seed_careers, seed_scholarships

    conn = dbmod.Connection(dbmod.connect())
    try:
        career_count = conn.execute("SELECT COUNT(*) AS n FROM careers").fetchone()["n"]
        if career_count < len(CAREERS):
            print(
                f"Seeding careers ({len(CAREERS)} total, {career_count} already present)...",
                flush=True,
            )
            seed_careers(
                conn,
                CAREERS,
                progress=lambda i, total: print(f"  {i}/{total} careers", flush=True),
            )
            conn.commit()
        else:
            print(f"Careers already seeded ({career_count}).", flush=True)

        sch_count = conn.execute("SELECT COUNT(*) AS n FROM scholarships").fetchone()["n"]
        if sch_count == 0:
            print(f"Seeding {len(SCHOLARSHIPS)} scholarships...", flush=True)
            seed_scholarships(conn, SCHOLARSHIPS)
            conn.commit()
        else:
            print(f"Scholarships already seeded ({sch_count}).", flush=True)

        from content_seed import seed_app_content
        print("Seeding exam calendar + verified career extras...", flush=True)
        seed_app_content(conn)
        conn.commit()

        n_careers = conn.execute("SELECT COUNT(*) AS n FROM careers").fetchone()["n"]
        n_sch = conn.execute("SELECT COUNT(*) AS n FROM scholarships").fetchone()["n"]
        print(f"Done. careers={n_careers} scholarships={n_sch}", flush=True)
    finally:
        conn.close()


def main():
    if not dbmod.DATABASE_URL:
        print("ERROR: DATABASE_URL not set (see .env)")
        sys.exit(1)

    # Show a safe-ish hint of the target (hide credentials)
    safe_target = dbmod.DATABASE_URL
    if "@" in safe_target:
        safe_target = safe_target.split("@", 1)[1]
    print(f"Target DB: {safe_target}")
    print()
    print("This will run:  DROP SCHEMA public CASCADE;  CREATE SCHEMA public;")
    print("ALL tables, views, data, and custom types will be permanently deleted.")
    print("Government job notifications are also deleted and are not re-seeded.")
    confirm = input("Type 'CLEARDB' to confirm: ").strip()
    if confirm != "CLEARDB":
        print("Aborted.")
        sys.exit(0)

    conn = dbmod.connect()
    try:
        with conn.cursor() as cur:
            cur.execute("DROP SCHEMA IF EXISTS public CASCADE;")
            cur.execute("CREATE SCHEMA public;")
        conn.commit()
        print("\nDatabase cleared. Initializing schema + seeds...", flush=True)
    finally:
        conn.close()

    init_schema_and_seeds()

    print("Database cleared and initialized successfully.")
    print("Users and gov-job rows were wiped. Recreate a demo login with:")
    print("  python create_demo_user.py")
    print("Ready. Start the server with: python main.py")


if __name__ == "__main__":
    main()
