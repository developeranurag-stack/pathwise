# Contributing to PathWise India

Thanks for wanting to help. This is a Flask + Postgres app with server-rendered
Jinja templates and Tailwind via CDN — there is no frontend build step.

Please read the [Code of Conduct](CODE_OF_CONDUCT.md) before opening an issue or
pull request.

## Ways to help

- Bug reports and small UX fixes
- Career / scholarship / exam data that you can cite from an official source
- Tests around matching, career seed data, or gov-job display helpers
- Docs that make local setup easier

Please **do not** open a PR that commits `.env`, API keys, or a live database
URL. Scholarship and career copy should be illustrative or sourced — do not
invent eligibility rules or deadlines.

## Local setup

Follow the **Run locally** section in [README.md](README.md). You need:

- Python 3.11+
- Postgres (Docker Compose in this repo, or any `DATABASE_URL`)

```bash
python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env              # then edit DATABASE_URL and SECRET_KEY
docker compose up -d              # optional, if you want local Postgres
python main.py
```

Optional: `OPENROUTER_API_KEY` is only required for `/assistant`.

## Architecture notes (short)

- Read careers through `career_app_view`, not by joining the normalized tables.
- Write careers via the multi-table fan-out in `save_career_admin()` /
  `seed_careers()` — the flat fields (`demand`, `skills`, `salary_min`, …) live
  on the view, not on `careers`.
- SQL in app code uses `?` placeholders; `db.Connection` rewrites them to `%s`.
- Matching lives in `matching.py`. The assistant in `assistant.py` is
  read-only against careers/scholarships (it can ingest gov-job ads).
- `career_id` is a UUID string. Scholarship IDs are integers.

Deeper context: [AGENTS.md](AGENTS.md) and [CLAUDE.md](CLAUDE.md).

## Tests

```bash
pip install pytest
python -m pytest tests/ -q
```

These tests do not need a database. They cover matching, gov-job display
helpers, and verified career seed shape.

## Pull requests

1. Fork and branch from `master`.
2. Keep the change focused. Match existing Python / Jinja style.
3. Run `python -m pytest tests/ -q` if you touched matching, careers, or
   gov-job helpers.
4. Describe *what* changed and *why*. Link an issue if there is one.

Schema changes: `schema.sql` is applied only when the `careers` table is
missing. There is no migration runner — document the SQL change in the PR,
and use `python clear_db.py` locally (destructive) if you need a clean slate.

## Reporting security issues

Do not file public issues for vulnerabilities. See [SECURITY.md](SECURITY.md).
