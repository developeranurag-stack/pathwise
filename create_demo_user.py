"""Creates (or resets) a demo account for staging, with a filled-in profile
and a few saved careers/scholarships so the app has something to show
immediately after deploy.

Usage: python create_demo_user.py
"""
import json

import db as dbmod
from main import init_db, now_iso
from werkzeug.security import generate_password_hash

DEMO_EMAIL = "demo@pathwise.in"
DEMO_PASSWORD = "demo1234"
DEMO_NAME = "Demo Student"

DEMO_PROFILE = dict(
    education_level="Class 11-12",
    state="Maharashtra",
    category="OBC",
    gender="Female",
    income_bracket=280000,
    interests=["tech", "science"],
    stream="pcm",
    board="CBSE",
    marks_band="75_90",
)

DEMO_SAVED_CAREER_SLUGS = ["software-engineer", "data-scientist", "registered-nurse"]
DEMO_SAVED_SCHOLARSHIP_NAMES = [
    "Post-Matric Scholarship for OBC Students",
    "Pragati Scholarship for Girls (AICTE)",
]


def main():
    init_db()
    conn = dbmod.Connection(dbmod.connect())

    existing = conn.execute("SELECT id FROM users WHERE email = ?", (DEMO_EMAIL,)).fetchone()
    if existing:
        user_id = existing["id"]
        conn.execute("UPDATE users SET password_hash = ? WHERE id = ?",
                     (generate_password_hash(DEMO_PASSWORD), user_id))
        print(f"Demo user already existed (id={user_id}); password reset.")
    else:
        cur = conn.execute(
            "INSERT INTO users (name, email, password_hash, created_at) VALUES (?,?,?,?) RETURNING id",
            (DEMO_NAME, DEMO_EMAIL, generate_password_hash(DEMO_PASSWORD), now_iso()),
        )
        user_id = cur.fetchone()["id"]
        print(f"Created demo user (id={user_id}).")

    conn.execute(
        """INSERT INTO profiles (user_id, education_level, state, category, gender,
           income_bracket, interests, stream, board, marks_band)
           VALUES (?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(user_id) DO UPDATE SET
             education_level=excluded.education_level, state=excluded.state,
             category=excluded.category, gender=excluded.gender,
             income_bracket=excluded.income_bracket, interests=excluded.interests,
             stream=excluded.stream, board=excluded.board, marks_band=excluded.marks_band""",
        (user_id, DEMO_PROFILE["education_level"], DEMO_PROFILE["state"],
         DEMO_PROFILE["category"], DEMO_PROFILE["gender"], DEMO_PROFILE["income_bracket"],
         json.dumps(DEMO_PROFILE["interests"]), DEMO_PROFILE["stream"],
         DEMO_PROFILE["board"], DEMO_PROFILE["marks_band"]),
    )

    for slug in DEMO_SAVED_CAREER_SLUGS:
        career = conn.execute("SELECT career_id FROM careers WHERE slug = ?", (slug,)).fetchone()
        if career:
            conn.execute(
                "INSERT INTO saved_careers (user_id, career_id, created_at) VALUES (?,?,?) ON CONFLICT DO NOTHING",
                (user_id, career["career_id"], now_iso()),
            )

    for name in DEMO_SAVED_SCHOLARSHIP_NAMES:
        sch = conn.execute("SELECT id FROM scholarships WHERE name = ?", (name,)).fetchone()
        if sch:
            conn.execute(
                "INSERT INTO saved_scholarships (user_id, scholarship_id, created_at) VALUES (?,?,?) ON CONFLICT DO NOTHING",
                (user_id, sch["id"], now_iso()),
            )

    conn.commit()
    conn.close()

    print(f"\nDemo login credentials:\n  Email:    {DEMO_EMAIL}\n  Password: {DEMO_PASSWORD}")


if __name__ == "__main__":
    main()
