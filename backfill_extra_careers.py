"""One-off backfill: loads seed_data.EXTRA_CAREERS (bulk-imported profession
titles from Arts/Commerce/Science stream lists) into an already-seeded DB.
Safe to run once; re-running will fail on the UNIQUE slug/career_code
constraints since seed_careers() has no ON CONFLICT handling."""
import db
from seed_data import EXTRA_CAREERS, seed_careers

conn = db.Connection(db.connect())
try:
    before = conn.execute("SELECT count(*) AS n FROM careers").fetchone()["n"]
    seed_careers(conn, EXTRA_CAREERS)
    conn.commit()
    after = conn.execute("SELECT count(*) AS n FROM careers").fetchone()["n"]
    print(f"careers: {before} -> {after} (+{after - before})")
finally:
    conn.close()
