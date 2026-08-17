# PathWise India (MVP)

Discover your future. Find the funding to reach it.

An MVP covering the core PathWise journey: profile-based career recommendations
(Step 1-2) and scholarship matching with a save/roadmap dashboard (Step 4-5).
Education-path details are folded into each career page (Step 3). AI chat
features, payments, and B2B dashboards are out of scope for this MVP.

## Stack

Flask + Postgres (Neon), server-rendered Jinja templates, Tailwind via CDN.

## Database schema

`schema.sql` defines two things: a normalized ~25-table career database (careers plus lookup/junction
tables for skills, exams, salary bands, demand, automation risk, etc.), and the app's own tables
(users, profiles, scholarships, saved items). Route code and templates never join the normalized
career tables directly — they read through `career_app_view`, which flattens everything into one row
per career (skills/exams aggregated via `string_agg`). The diagram below covers the tables that are
actually wired into the app today:

```mermaid
erDiagram
    career_categories ||--o{ careers : categorizes
    careers ||--|| career_demand : has
    careers ||--|| career_automation_risk : has
    careers ||--o{ career_salary_india : "has (per level)"
    careers ||--o{ career_skills : ""
    skills ||--o{ career_skills : ""
    careers ||--o{ career_entrance_exams : ""
    entrance_exams ||--o{ career_entrance_exams : ""
    users ||--|| profiles : has
    users ||--o{ saved_careers : saves
    careers ||--o{ saved_careers : ""
    users ||--o{ saved_scholarships : saves
    scholarships ||--o{ saved_scholarships : ""

    career_categories {
        int category_id PK
        text name UK
    }
    careers {
        uuid career_id PK
        text career_code UK
        text career_name
        text slug UK
        int career_category_id FK
        text description
        text min_education_qualification
        text source "manual | scraper:<name>"
    }
    career_demand {
        uuid career_id PK "FK to careers"
        enum current_demand
        enum future_demand
    }
    career_salary_india {
        int id PK
        uuid career_id FK
        text level "Entry/Mid/Senior/Leadership/Highest"
        numeric min_salary_inr
        numeric max_salary_inr
    }
    career_automation_risk {
        uuid career_id PK "FK to careers"
        enum risk_level
        text future_proof_recommendation
    }
    skills {
        int skill_id PK
        text name UK
        enum skill_type "Technical | Soft"
    }
    career_skills {
        uuid career_id FK
        int skill_id FK
    }
    entrance_exams {
        int exam_id PK
        text name UK
        enum exam_type
    }
    career_entrance_exams {
        uuid career_id FK
        int exam_id FK
    }
    users {
        int id PK
        text email UK
        text password_hash
        bool is_admin
    }
    profiles {
        int user_id PK "FK to users"
        text education_level
        text state
        text category
        text gender
        int income_bracket
        text interests "JSON list of interest-cluster keys"
    }
    scholarships {
        int id PK
        text name
        text education_level
        text states "CSV or 'All'"
        text categories "CSV or 'All'"
        text gender
        int income_ceiling
        text source "manual | scraper:<name>"
    }
    saved_careers {
        int user_id FK
        uuid career_id FK
        text created_at
    }
    saved_scholarships {
        int user_id FK
        int scholarship_id FK
        text status
    }
```

`career_app_view` (not shown as a table above — it's a `SELECT` over `careers` LEFT JOINed to
`career_categories`, `career_demand`, `career_salary_india` (`level = 'Entry Level (0-3 Yrs)'`), and
`career_automation_risk`, with skills/exams aggregated via correlated subqueries) is what
`career_category.name` doubles as: the onboarding interest-cluster key (`tech`, `business`, `law`, ...)
consumed by `recommended_career_ids()`.

`sources` (scraper config: name, URL, parser) isn't a real foreign key relationship — it's linked to
`careers`/`scholarships` only loosely, by convention, via the `source` text column (`'scraper:<source
name>'`) so re-scraping a source only overwrites rows it previously wrote, never manually-entered ones.

`schema.sql` also defines ~25 more normalized tables (`industries`, `streams`, `degrees`,
`career_work_life_balance`, `career_remote_work`, `riasec_types`, `mbti_types`, `core_strengths`,
`subjects`, `recruiters`, `certifications`, `career_internships`, `learning_resources`, `countries`,
`career_advantages`, `career_challenges`, `career_roadmap_steps`, `comparison_metrics`,
`growth_drivers`, `employment_opportunity_types`, `career_progression_roles`,
`career_related_industries`, `career_international_opportunities`, and their junction tables) plus a
`career_summary` view. These exist for a richer future career-explorer/compare experience but aren't
read by any current route or template — omitted above to keep the diagram legible.

## Run locally

```
python -m venv venv
./venv/Scripts/pip install -r requirements.txt   # venv/bin/pip on macOS/Linux
```

Copy `.env.example` to `.env` and fill in `DATABASE_URL` with your Postgres connection string
(e.g. a Neon connection string).

```
./venv/Scripts/python main.py                     # venv/bin/python on macOS/Linux
```

Visit http://127.0.0.1:5000. The schema (`schema.sql`) and seed data (careers, scholarships)
are created automatically on first run against an empty database, from `seed_data.py`.

## Demo user (staging)

Run `python create_demo_user.py` after the database exists (or it will create one)
to set up a demo account with a filled-in profile and a few saved careers/scholarships.

To completely wipe + re-initialize the DB (e.g. after editing `schema.sql`):
```
python clear_db.py
```
(DB is cleared and re-seeded immediately; then you can start the server.)

- Email: `demo@pathwise.in`
- Password: `demo1234`

Re-running the script resets the password and refreshes the demo profile/saved
items — safe to run on every staging deploy.

## What's implemented

- Auth: register / login / logout (session-based, hashed passwords)
- Onboarding quiz: education level, state, category, gender, income, interests
- Career explorer: browse/filter by interest cluster, detail pages with salary,
  demand, skills, AI impact, education path, exams
- Scholarship finder: browse/filter by type, eligibility matching against the
  student's profile (education level, state, category, gender, income ceiling)
- Dashboard/roadmap: saved careers & scholarships, deadline visibility,
  personalized recommendations

## Not yet built

AI chat assistant, resume/essay review, application checklist/document tracking,
reminders, premium billing, school/counselor (B2B) dashboards.

Scholarship data is illustrative for demo purposes — verify current eligibility
and deadlines on official portals before applying.
