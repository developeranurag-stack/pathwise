"""Postgres (Neon) connection helpers, shared by main.py and the one-off scripts."""
import os

import psycopg
from psycopg.rows import dict_row
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.environ.get("DATABASE_URL")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SCHEMA_PATH = os.path.join(BASE_DIR, "schema.sql")


def connect():
    if not DATABASE_URL:
        raise RuntimeError(
            "DATABASE_URL is not set. Create a .env file with your Neon connection "
            "string, e.g. DATABASE_URL=postgresql://user:pass@host/dbname?sslmode=require"
        )
    conn = psycopg.connect(DATABASE_URL, row_factory=dict_row)
    return conn


class Connection:
    """Thin sqlite3-style wrapper around a psycopg connection.

    Lets route code keep writing `db.execute("... WHERE x = ?", (val,))` and
    get back a cursor with .fetchone()/.fetchall(), the way it did against
    sqlite3. `?` placeholders are translated to psycopg's `%s`.
    """

    def __init__(self, conn):
        self._conn = conn

    def execute(self, sql, params=()):
        cur = self._conn.cursor()
        cur.execute(sql.replace("?", "%s"), params)
        return cur

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        self._conn.close()

    def cursor(self):
        return self._conn.cursor()


CAREER_APP_VIEW_SQL = """
CREATE OR REPLACE VIEW career_app_view AS
SELECT
    c.career_id,
    c.career_code,
    c.slug,
    c.career_name AS name,
    cc.name AS cluster,
    c.description,
    d.current_demand::TEXT AS demand,
    d.future_demand::TEXT AS future_demand,
    sal.min_salary_inr::BIGINT AS salary_min,
    sal.max_salary_inr::BIGINT AS salary_max,
    sal_mid.min_salary_inr::BIGINT AS salary_mid_min,
    sal_mid.max_salary_inr::BIGINT AS salary_mid_max,
    (SELECT string_agg(s.name, ', ' ORDER BY s.name)
       FROM career_skills cs JOIN skills s ON s.skill_id = cs.skill_id
       WHERE cs.career_id = c.career_id) AS skills,
    ar.future_proof_recommendation AS ai_impact,
    ar.risk_level::TEXT AS automation_risk,
    c.min_education_qualification AS education_path,
    (SELECT string_agg(e.name, ', ' ORDER BY e.name)
       FROM career_entrance_exams ce JOIN entrance_exams e ON e.exam_id = ce.exam_id
       WHERE ce.career_id = c.career_id) AS exams,
    (SELECT string_agg(r.code, '' ORDER BY r.code)
       FROM career_riasec cr JOIN riasec_types r ON r.riasec_id = cr.riasec_id
       WHERE cr.career_id = c.career_id) AS riasec,
    wlb.rating::TEXT AS wlb,
    rw.potential::TEXT AS remote_work,
    c.is_verified,
    c.source,
    c.source_url,
    c.last_synced_at
FROM careers c
LEFT JOIN career_categories cc            ON cc.category_id = c.career_category_id
LEFT JOIN career_demand d                 ON d.career_id = c.career_id
LEFT JOIN career_salary_india sal         ON sal.career_id = c.career_id AND sal.level = 'Entry Level (0-3 Yrs)'
LEFT JOIN career_salary_india sal_mid     ON sal_mid.career_id = c.career_id AND sal_mid.level = 'Mid-Level (4-8 Yrs)'
LEFT JOIN career_automation_risk ar       ON ar.career_id = c.career_id
LEFT JOIN career_work_life_balance wlb    ON wlb.career_id = c.career_id
LEFT JOIN career_remote_work rw           ON rw.career_id = c.career_id
"""


def migrate_schema():
    """Additive upgrades for databases created before the latest schema.sql."""
    conn = connect()
    try:
        statements = [
            "ALTER TABLE careers ADD COLUMN IF NOT EXISTS is_verified BOOLEAN NOT NULL DEFAULT FALSE",
            "ALTER TABLE profiles ADD COLUMN IF NOT EXISTS stream TEXT",
            "ALTER TABLE profiles ADD COLUMN IF NOT EXISTS board TEXT",
            "ALTER TABLE profiles ADD COLUMN IF NOT EXISTS marks_band TEXT",
            "ALTER TABLE profiles ADD COLUMN IF NOT EXISTS subjects TEXT",
            "ALTER TABLE profiles ADD COLUMN IF NOT EXISTS has_disability BOOLEAN NOT NULL DEFAULT FALSE",
            "ALTER TABLE profiles ADD COLUMN IF NOT EXISTS is_first_generation BOOLEAN NOT NULL DEFAULT FALSE",
            "ALTER TABLE profiles ADD COLUMN IF NOT EXISTS is_rural BOOLEAN NOT NULL DEFAULT FALSE",
            "ALTER TABLE profiles ADD COLUMN IF NOT EXISTS is_minority BOOLEAN NOT NULL DEFAULT FALSE",
            "ALTER TABLE profiles ADD COLUMN IF NOT EXISTS language_pref TEXT NOT NULL DEFAULT 'en'",
            "ALTER TABLE profiles ADD COLUMN IF NOT EXISTS riasec_codes TEXT",
            "ALTER TABLE scholarships ADD COLUMN IF NOT EXISTS requires_disability BOOLEAN NOT NULL DEFAULT FALSE",
            "ALTER TABLE scholarships ADD COLUMN IF NOT EXISTS requires_minority BOOLEAN NOT NULL DEFAULT FALSE",
            """CREATE TABLE IF NOT EXISTS checklist_items (
                id SERIAL PRIMARY KEY,
                user_id INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                item_type TEXT NOT NULL,
                ref_id TEXT,
                label TEXT NOT NULL,
                done BOOLEAN NOT NULL DEFAULT FALSE,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                UNIQUE (user_id, item_type, ref_id, label)
            )""",
            """CREATE TABLE IF NOT EXISTS assistant_messages (
                id SERIAL PRIMARY KEY,
                user_id INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )""",
            "CREATE INDEX IF NOT EXISTS idx_assistant_messages_user ON assistant_messages(user_id, id)",
            """CREATE TABLE IF NOT EXISTS share_links (
                token TEXT PRIMARY KEY,
                user_id INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )""",
            """CREATE TABLE IF NOT EXISTS exam_calendar (
                id SERIAL PRIMARY KEY,
                exam_name TEXT NOT NULL UNIQUE,
                exam_code TEXT,
                typical_window TEXT,
                typical_month SMALLINT,
                next_cycle TEXT,
                education_level TEXT,
                streams TEXT,
                clusters TEXT,
                official_url TEXT,
                notes TEXT
            )""",
            """CREATE TABLE IF NOT EXISTS career_institutes (
                id SERIAL PRIMARY KEY,
                career_id UUID NOT NULL REFERENCES careers(career_id) ON DELETE CASCADE,
                name TEXT NOT NULL,
                kind TEXT,
                entrance TEXT,
                typical_fees TEXT,
                notes TEXT
            )""",
            """CREATE TABLE IF NOT EXISTS related_careers (
                career_id UUID NOT NULL REFERENCES careers(career_id) ON DELETE CASCADE,
                related_career_id UUID NOT NULL REFERENCES careers(career_id) ON DELETE CASCADE,
                PRIMARY KEY (career_id, related_career_id)
            )""",
            """CREATE TABLE IF NOT EXISTS saved_gov_jobs (
                user_id INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                notification_id INT NOT NULL REFERENCES gov_job_notifications(id) ON DELETE CASCADE,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                PRIMARY KEY (user_id, notification_id)
            )""",
            "CREATE INDEX IF NOT EXISTS idx_careers_verified ON careers(is_verified)",
            "CREATE INDEX IF NOT EXISTS idx_exam_calendar_month ON exam_calendar(typical_month)",
            "CREATE INDEX IF NOT EXISTS idx_career_institutes_career ON career_institutes(career_id)",
            """CREATE TABLE IF NOT EXISTS app_meta (
                key TEXT PRIMARY KEY,
                value TEXT
            )""",
            "CREATE INDEX IF NOT EXISTS idx_careers_name_trgm ON careers USING gin (career_name gin_trgm_ops)",
        ]
        with conn.cursor() as cur:
            for sql in statements:
                cur.execute(sql)
            cur.execute("DROP VIEW IF EXISTS career_app_view")
            cur.execute(CAREER_APP_VIEW_SQL)
        conn.commit()
    finally:
        conn.close()


def init_db():
    """Creates the schema on first run, then applies additive migrations."""
    conn = connect()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT to_regclass('public.careers')")
            exists = cur.fetchone()["to_regclass"] is not None
        if not exists:
            with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
                schema_sql = f.read()
            with conn.cursor() as cur:
                cur.execute(schema_sql)
            conn.commit()
    finally:
        conn.close()

    migrate_schema()
    return not exists
