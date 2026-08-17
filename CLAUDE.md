# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

PathWise India (MVP): a Flask app that recommends careers to Indian students based on an onboarding
profile, and matches them against scholarships. Career pages fold in education-path detail; a
save/roadmap dashboard lets students track careers and scholarships they're interested in. An agentic
assistant (`/assistant`) lets students chat their way to career/scholarship matches. Payments and B2B
(school/counselor) dashboards are explicitly out of scope for this MVP.

## Stack

Flask + Postgres (Neon), server-rendered Jinja templates, Tailwind via CDN. No frontend build step —
`static/css` and `static/js` are served as-is.

The app was originally SQLite; it now runs against Postgres exclusively via `psycopg` v3 (not
`psycopg2` — that package has no prebuilt wheel for this repo's Python 3.14 venv and fails to compile
from source; `psycopg[binary]` was used instead).

## Commands

```
./venv/Scripts/pip install -r requirements.txt   # venv/bin/pip on macOS/Linux
./venv/Scripts/python main.py                     # venv/bin/python on macOS/Linux
```

Visit http://127.0.0.1:5000. Requires a `.env` file with `DATABASE_URL` pointing at a Postgres
instance (see `.env.example`) — the app will raise on startup without it. Schema and seed data
(careers, scholarships) are created automatically on first run against an empty database.

Demo account (safe to re-run on every deploy — resets password and refreshes profile/saved items):
```
python create_demo_user.py     # demo@pathwise.in / demo1234
```

Promote a registered user to admin (`/admin`):
```
python make_admin.py user@example.com
```

Completely clear + re-initialize the database (for schema changes or fresh start):
```
python clear_db.py
```
(Confirm with CLEARDB when prompted. Script drops then immediately recreates schema + seeds via init. Ready to use, no need to start server first.)

There is no test suite, linter, or build step configured in this repo.

## Architecture

**`db.py`** — all Postgres access goes through this module. It exposes:
- `connect()` — raw `psycopg` connection with `dict_row` factory.
- `Connection` — a thin sqlite3-style wrapper (`.execute(sql_with_?, params)` → cursor with
  `.fetchone()`/`.fetchall()`) so the rest of the app can write queries the same way the original
  SQLite version did. **`?` placeholders are translated to `%s` inside this wrapper** — write new
  queries using `?`, not `%s`, unless you're using a raw `psycopg` connection directly (as
  `make_admin.py` does).
- `init_db()` — runs `schema.sql` once, only if the `careers` table doesn't exist yet. Idempotent.

**`schema.sql`** — two halves in one file:
1. A normalized, ~25-table career database (`careers`, `career_categories`, `skills`,
   `career_skills`, `career_salary_india`, `career_demand`, `career_automation_risk`,
   `entrance_exams`, etc.) using Postgres ENUMs for controlled-vocabulary fields
   (`demand_level`, `automation_risk`, `wlb_rating`, ...). `careers.career_id` is a UUID.
2. The app's own tables — `users`, `profiles`, `scholarships`, `sources`, `saved_careers`,
   `saved_scholarships` — which reference `careers.career_id`.

Critically, **`career_app_view`** flattens the normalized career tables back into one row per career
(`career_id, slug, name, cluster, description, demand, salary_min, salary_max, skills, ai_impact,
education_path, exams, ...`) with skills/exams aggregated via `string_agg`. Route code and templates
read careers through this view, not by joining the underlying tables directly — that's what keeps
`main.py` and the Jinja templates simple despite the richer schema underneath. `cluster` in the view
is `career_categories.name`, and doubles as the onboarding interest-cluster key (`tech`, `science`,
`business`, ... — see `INTEREST_CLUSTERS` in `seed_data.py`); it is *not* a separate concept from
career category.

Writing a career (admin create/edit, or the scraper) is a fan-out across multiple tables — see
`save_career_admin()` in `main.py` and `seed_careers()` in `seed_data.py` for the pattern: upsert the
category lookup, upsert/insert the core `careers` row, then upsert `career_demand` (mapping free-text
demand onto the ENUM), `career_salary_india` (always written at the `'Entry Level (0-3 Yrs)'` level —
that's the row `career_app_view` reads), `career_automation_risk`, and replace the `career_skills` /
`career_entrance_exams` junction rows. Skills and exams are entered/edited as comma-separated text and
get-or-created into their lookup tables by name.

**`main.py`** — single-file Flask app: routes, DB helpers, auth, matching logic, and admin CRUD all
live here (no blueprints). Session-based auth with Werkzeug password hashing; `current_user()` /
`current_profile()` read from `g`-cached request-scoped state. `admin_required` gates `/admin/*` on
`users.is_admin`.

**Matching/recommendation logic** (in `main.py`, not in SQL):
- `recommended_career_ids()` — matches a student's onboarding `interests` (JSON list stored in
  `profiles.interests`) against `career_app_view.cluster`.
- `scholarship_matches_profile()` — loose containment matching on education level, plus exact/`"All"`
  matching on state, category, gender, and an income ceiling comparison. `parse_list()` handles the
  comma-separated `states`/`categories` columns on `scholarships`.

**`seed_data.py`** — holds both the demo `CAREERS`/`SCHOLARSHIPS`/`INTEREST_CLUSTERS` data *and* the
functions that load it into the normalized schema (`seed_careers()`, `seed_scholarships()`), invoked
by `main.py:init_db()` only when the respective table is empty. `_DEMAND_MAP` /
`_FUTURE_DEMAND_MAP` normalize the seed data's free-text demand labels onto the schema's ENUMs — apply
the same normalization if you add more seed careers with novel demand values.

**`scraper.py`** — pluggable ingestion for careers/scholarships from external listing pages. A
`sources` DB row pairs a URL with a named parser (currently only `generic_html_table`, which needs a
static HTML `<table>` — JS-rendered/SPA sites need a new parser function registered in `PARSERS`).
Scraped rows are tagged `source='scraper:<source name>'`; on re-run, a scraped row only overwrites an
existing row if that existing row came from the *same* source tag — manually-entered rows (`source
='manual'`) are never clobbered by a scrape.

**`assistant.py`** — the agentic assistant: a function-calling loop (`run_agent_turn()`), run against
a model on OpenRouter (`OpenAI(base_url=OPENROUTER_BASE_URL, ...)`, default model
`openai/gpt-4o-mini`, overridable via `OPENROUTER_MODEL` — the `openai` package is used purely as an
HTTP client here, OpenRouter is an API gateway that proxies many providers' models), over read-only
tools (`search_careers`, `get_career_details`, `search_scholarships`, `get_student_profile`) backed by
`career_app_view`/`scholarships` and the same `scholarship_matches_profile()` helper `main.py` uses
elsewhere — the agent never writes to the database and never invents career/scholarship facts outside
what its tools return. Wired into `main.py` via `GET/POST /assistant`, `POST /assistant/message` (JSON
API — the app's only `jsonify` route), and `POST /assistant/reset`; conversation history is kept in
the Flask session (capped at the last ~12 messages), not a DB table. Requires `OPENROUTER_API_KEY` in
`.env`; unlike `DATABASE_URL` this is checked lazily at request time, so its absence degrades
`/assistant` gracefully instead of crashing app startup.

**Templates** — server-rendered Jinja under `templates/`, Tailwind via CDN (no build step), mobile-first
with a bottom action bar pattern on career/scholarship detail pages (see `career_detail.html`). Admin
views live under `templates/admin/`.

## Working with career data

- Read paths (career list/detail, dashboard, recommendations) should go through `career_app_view`.
- Write paths (admin forms, scraper) must go through the multi-table fan-out pattern, not a direct
  `UPDATE careers SET ...` with the old flat field names — those columns (`cluster`, `demand`,
  `salary_min`, `skills`, `ai_impact`, `exams`) don't exist on the `careers` table itself anymore.
- `career_id` is a UUID string, not an int — route params for career routes are untyped (`<career_id>`),
  not `<int:career_id>`.
