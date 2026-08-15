"""Promote an existing user to admin so they can access /admin.

Usage: python make_admin.py user@example.com
"""
import sys

import db as dbmod

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python make_admin.py <email>")
        sys.exit(1)

    email = sys.argv[1].strip().lower()
    conn = dbmod.connect()
    cur = conn.cursor()
    cur.execute("UPDATE users SET is_admin = TRUE WHERE email = %s", (email,))
    conn.commit()
    if cur.rowcount == 0:
        print(f"No user found with email {email}. Register that account first, then re-run this.")
    else:
        print(f"{email} is now an admin. Log in and visit /admin.")
    conn.close()
