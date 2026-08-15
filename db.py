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


def init_db():
    """Creates the schema on first run. Safe to call on every startup."""
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
        return not exists
    finally:
        conn.close()
