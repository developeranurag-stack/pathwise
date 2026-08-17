"""Clear the database by dropping the entire 'public' schema, then initialize it.

This gives a completely fresh DB with schema + seed data (careers + scholarships).

After running this the DB is ready; you can start the server or run create_demo_user.py.

Usage:
  python clear_db.py

WARNING: DESTRUCTIVE. Destroys ALL data in the connected database.
"""
import sys

import db as dbmod


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
        print("\nDatabase cleared. Initializing schema + seeds...")
    finally:
        conn.close()

    # Importing main executes its top-level init_db() which (re)creates the schema
    # from schema.sql and seeds careers/scholarships (tables are empty after the drop).
    import main

    print("Database cleared and initialized successfully.")
    print("Ready. Start the server with: python main.py")


if __name__ == "__main__":
    main()
