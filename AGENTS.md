# AGENTS.md

Compact guidance for working in this PathWise India Flask repo. Consult `CLAUDE.md` for deeper architecture details.

## Setup
- `python -m venv venv`
- Windows: `./venv/Scripts/pip install -r requirements.txt`
- macOS/Linux: `./venv/bin/pip install -r requirements.txt`
- Copy `.env.example` → `.env` (required: `DATABASE_URL` to Postgres/Neon; `OPENROUTER_API_KEY` only for `/assistant`)
- Run: Windows `./venv/Scripts/python main.py`; macOS/Linux `./venv/bin/python main.py`
- Visits http://127.0.0.1:5000 (or PORT). `init_db()` auto-runs `schema.sql` + seeds only on empty DB (first run or after drop).

## Essential one-off commands
- `python create_demo_user.py` — creates/resets `demo@pathwise.in` / `demo1234` (safe to rerun; refreshes profile + saves)
- `python make_admin.py user@example.com` — promotes registered user for `/admin` access
- `python backfill_extra_careers.py` — one-time load of EXTRA_CAREERS (fails on re-run due to UNIQUE constraints)
- `python clear_db.py` — **destructive** full wipe + re-init (`DROP SCHEMA public CASCADE;` then schema+seeds). Use to reset after schema.sql edits or for clean slate. DB is ready immediately after (no need to start server first).

No test/lint/typecheck/build commands exist.

## DB and query rules (critical)
- All app code uses `get_db()` → `db.Connection` wrapper (from `db.py`).
- Write queries with `?` placeholders (e.g. `WHERE x = ?`); wrapper rewrites to `%s` for psycopg.
- Use `%s` + raw `psycopg` cursor **only** in one-off scripts that call `dbmod.connect()` directly (e.g. `make_admin.py`).
- `db.py` does `load_dotenv()` on import; `.env` must exist before any DB-using import or startup crashes.
- `teardown_appcontext` auto-commits on success, rolls back on exception.

## Career data (never bypass)
- Read-only paths (lists, details, dashboard, recs, assistant tools) **must** `SELECT * FROM career_app_view`.
- Write paths (admin CRUD, scraper, seed) use fan-out in `save_career_admin()` / `seed_careers()`:
  - upsert category → core `careers` row (UUID `career_id`, code, slug) → `career_demand`, `career_salary_india` (always at level `'Entry Level (0-3 Yrs)'`), `career_automation_risk` → replace `career_skills` / `career_entrance_exams` junctions.
  - Skills/exams entered as comma lists; get-or-created into lookups.
- Never `UPDATE careers SET ...` with flat fields (`demand`, `skills`, `salary_min` etc.) — those live only in the view.
- Public career URLs use slug: `/careers/<slug>`; admin uses raw UUID `/admin/careers/<career_id>`.
- `career_id` is UUID str (not int). Scholarships use serial int IDs everywhere.
- Seed demand normalization: `_DEMAND_MAP` / `_FUTURE_DEMAND_MAP` in `seed_data.py` (e.g. "Moderate"→"Medium", "Growing"→"High"). Admin form posts schema ENUM values directly.

## Matching / recommendations
- `recommended_career_ids(profile, db)`: matches `profiles.interests` (JSON array of cluster keys) to `career_app_view.cluster` (== category name).
- `scholarship_matches_profile(sch, profile)`: education loose-contains, state/category/gender exact or "All", income ceiling check. Reused by assistant.
- Both live in `main.py`; assistant receives the matcher as arg (never reimplements).

## Assistant (`/assistant`)
- Requires `OPENROUTER_API_KEY` (lazy; absence returns error only on use). Uses `openai` client against OpenRouter, default `openai/gpt-4o-mini` (override `OPENROUTER_MODEL`).
- `run_agent_turn()` is tool-calling loop (max 5 iters). Can read careers/scholarships/gov jobs + write new gov job notifications when user provides ad text/material (historical records are always kept because vacancies recur in following years).
- Replies in Hindi (Devanagari) by default but switches to English if user writes in English or asks to "talk in English". Keeps proper nouns in English. History capped at ~12 msgs in Flask session (not DB). Reset via POST `/assistant/reset`.
- Tools: `search_careers`, `get_career_details`, `search_scholarships`, `get_student_profile`, `search_gov_jobs`, `get_gov_job_details`, `ingest_gov_job` (writes only gov jobs from user-provided ad material; historical records kept because vacancies recur).

## Government jobs
- Read-only UI at `/gov-jobs*` (populated from `gov_job_notifications` + `gov_job_posts`). All historical notifications are kept forever (vacancies recur in following years).
- The assistant can search them, show details, and directly ingest new ones via `ingest_gov_job` when user pastes ad text/screenshots (bypasses or supplements MCP).
- Upload PDFs (admin) to `../pathwise-mcp/tobepicked/` for MCP processing; direct AI ingest also supported via the assistant or `direct_ingest_gov_job.py` script.
- `.mcp.json` points at the MCP server (paths are dev-machine specific).

## Scraping / sources (admin only)
- `/admin/sources/*`: configure URL + parser name; run via POST triggers `scraper.run_source()`.
- Scraped rows tagged `source='scraper:<name>'`; re-runs overwrite only same-source rows (manual `'manual'` rows protected).
- Add new parsers in `scraper.PARSERS` (currently only `generic_html_table` for static `<table>` pages).

## Admin / auth
- Session-based (Werkzeug hashes). `current_user()` / `current_profile()` cached in `g`.
- `/admin/*` gated by `users.is_admin`.
- Onboarding writes `profiles` (interests as JSON list of cluster keys from `seed_data.INTEREST_CLUSTERS`).
- `SECRET_KEY` defaults to dev value; set in prod `.env`.

## Schema / seeding notes
- `schema.sql` is monolithic + idempotent (ENUMs, tables, view, indexes). `db.init_db()` runs full file **only** if `careers` table missing.
- Editing `schema.sql` after first run: manual apply or `DROP` the DB (no migration runner).
- ~25 normalized tables exist; only core + `career_app_view`, `users`/`profiles`/`scholarships`/`saved_*`/`sources`/`gov_job_*` are exercised by current code.
- Seed data (including `EXTRA_CAREERS`) is demo/illustrative only.

## Other
- Tailwind via CDN only (no `static/` build). All in `templates/` (Jinja) + inline in `base.html`.
- `app.run(debug=True)` always when run as main.
- `.gitignore`: `venv/`, `.env`, `pathwise.db` (legacy), `__pycache__`, etc.
- No monorepo packages; single Python package boundary. Sibling `pathwise-mcp` is separate repo for MCP/gov-job PDF extraction only.
