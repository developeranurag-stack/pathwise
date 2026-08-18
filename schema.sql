-- ============================================================================
-- PATHWISE MASTER SCHEMA (PostgreSQL / Neon)
-- Combines the normalized career database (careers + lookup/junction tables)
-- with the app's own tables (users, profiles, scholarships, saved items).
-- Executed once, in full, the first time the app connects to an empty database
-- (see db.py:init_db). Safe to re-run: every statement is idempotent.
-- ============================================================================

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- ----------------------------------------------------------------------------
-- ENUM TYPES (created only if missing, so re-running this file is safe)
-- ----------------------------------------------------------------------------
DO $$ BEGIN
    CREATE TYPE demand_level AS ENUM ('Very High','High','Medium','Low');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN
    CREATE TYPE future_demand_level AS ENUM ('Very High','High','Medium','Declining');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN
    CREATE TYPE automation_risk AS ENUM ('Very Low','Low','Moderate','High','Very High');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN
    CREATE TYPE wlb_rating AS ENUM ('Excellent','Good','Average','Demanding','Highly Demanding');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN
    CREATE TYPE remote_potential AS ENUM ('Fully Remote','Mostly Remote','Hybrid','Mostly On-site','Completely On-site');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN
    CREATE TYPE entrepreneurship_level AS ENUM ('Very High','High','Moderate','Low');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN
    CREATE TYPE progression_level AS ENUM ('Entry-Level','Mid-Level','Senior','Leadership','Executive','Alternate Path');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN
    CREATE TYPE skill_type AS ENUM ('Technical','Soft');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN
    CREATE TYPE degree_link_type AS ENUM ('Recommended','Alternative','Diploma','Certification Route','Higher Education');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN
    CREATE TYPE exam_type AS ENUM ('National','State','Institution-Specific','Professional Licensing','Competitive Government');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN
    CREATE TYPE employer_sector AS ENUM ('Government','Private');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN
    CREATE TYPE certification_level AS ENUM ('Beginner','Intermediate','Advanced','Industry-Recognized');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN
    CREATE TYPE internship_stage AS ENUM ('During College','After Graduation','Government','Industry','Research');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN
    CREATE TYPE resource_type AS ENUM ('Book','Online Course','YouTube Channel','Website','Podcast','Newsletter','Professional Community');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN
    CREATE TYPE roadmap_stage AS ENUM ('After Class 10','After Class 12','During Graduation','Skill Development','Internships','First Job','Career Growth Milestones');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN
    CREATE TYPE industry_relation AS ENUM ('Primary','Related','Emerging','Fastest Growing');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

-- ----------------------------------------------------------------------------
-- CORE CAREER TABLES
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS career_categories (
    category_id     SERIAL PRIMARY KEY,
    name            TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS industries (
    industry_id     SERIAL PRIMARY KEY,
    name            TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS careers (
    career_id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    career_code                TEXT NOT NULL UNIQUE,
    career_name                TEXT NOT NULL,
    slug                       TEXT NOT NULL UNIQUE,
    career_category_id         INT REFERENCES career_categories(category_id),
    primary_industry_id        INT REFERENCES industries(industry_id),
    description                TEXT,
    job_responsibilities       TEXT,
    min_education_qualification TEXT,
    age_requirement             TEXT,
    entrepreneurship_potential  entrepreneurship_level,
    entrepreneurship_notes       TEXT,
    source                       TEXT NOT NULL DEFAULT 'manual',
    source_url                   TEXT,
    last_synced_at                TIMESTAMPTZ,
    is_verified                  BOOLEAN NOT NULL DEFAULT FALSE,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_careers_category ON careers(career_category_id);
CREATE INDEX IF NOT EXISTS idx_careers_industry ON careers(primary_industry_id);
CREATE INDEX IF NOT EXISTS idx_careers_name_trgm ON careers USING gin (career_name gin_trgm_ops);

CREATE TABLE IF NOT EXISTS career_alt_titles (
    id          SERIAL PRIMARY KEY,
    career_id   UUID NOT NULL REFERENCES careers(career_id) ON DELETE CASCADE,
    alt_title   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS streams (
    stream_id   SERIAL PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS career_streams (
    career_id   UUID NOT NULL REFERENCES careers(career_id) ON DELETE CASCADE,
    stream_id   INT NOT NULL REFERENCES streams(stream_id),
    PRIMARY KEY (career_id, stream_id)
);

CREATE TABLE IF NOT EXISTS degrees (
    degree_id   SERIAL PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS career_degrees (
    career_id   UUID NOT NULL REFERENCES careers(career_id) ON DELETE CASCADE,
    degree_id   INT NOT NULL REFERENCES degrees(degree_id),
    link_type   degree_link_type NOT NULL,
    PRIMARY KEY (career_id, degree_id, link_type)
);

CREATE TABLE IF NOT EXISTS entrance_exams (
    exam_id     SERIAL PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,
    exam_type   exam_type NOT NULL
);

CREATE TABLE IF NOT EXISTS career_entrance_exams (
    career_id   UUID NOT NULL REFERENCES careers(career_id) ON DELETE CASCADE,
    exam_id     INT NOT NULL REFERENCES entrance_exams(exam_id),
    PRIMARY KEY (career_id, exam_id)
);

CREATE TABLE IF NOT EXISTS skills (
    skill_id    SERIAL PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,
    skill_type  skill_type NOT NULL
);

CREATE TABLE IF NOT EXISTS career_skills (
    career_id   UUID NOT NULL REFERENCES careers(career_id) ON DELETE CASCADE,
    skill_id    INT NOT NULL REFERENCES skills(skill_id),
    PRIMARY KEY (career_id, skill_id)
);

CREATE TABLE IF NOT EXISTS career_salary_india (
    id              SERIAL PRIMARY KEY,
    career_id       UUID NOT NULL REFERENCES careers(career_id) ON DELETE CASCADE,
    level           TEXT NOT NULL CHECK (level IN ('Entry Level (0-3 Yrs)','Mid-Level (4-8 Yrs)','Senior Level (9-15 Yrs)','Leadership Level','Highest Reported')),
    min_salary_inr  NUMERIC(12,2),
    max_salary_inr  NUMERIC(12,2),
    UNIQUE (career_id, level)
);

CREATE TABLE IF NOT EXISTS career_salary_international (
    id              SERIAL PRIMARY KEY,
    career_id       UUID NOT NULL REFERENCES careers(career_id) ON DELETE CASCADE,
    country         TEXT NOT NULL CHECK (country IN ('USA','UK','Canada','Australia','UAE','Singapore','Europe')),
    min_salary      NUMERIC(12,2),
    max_salary      NUMERIC(12,2),
    currency        TEXT NOT NULL,
    UNIQUE (career_id, country)
);

CREATE TABLE IF NOT EXISTS career_demand (
    career_id       UUID PRIMARY KEY REFERENCES careers(career_id) ON DELETE CASCADE,
    current_demand  demand_level NOT NULL,
    future_demand   future_demand_level NOT NULL
);

CREATE TABLE IF NOT EXISTS growth_drivers (
    driver_id   SERIAL PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS career_growth_drivers (
    career_id   UUID NOT NULL REFERENCES careers(career_id) ON DELETE CASCADE,
    driver_id   INT NOT NULL REFERENCES growth_drivers(driver_id),
    PRIMARY KEY (career_id, driver_id)
);

CREATE TABLE IF NOT EXISTS career_automation_risk (
    career_id                   UUID PRIMARY KEY REFERENCES careers(career_id) ON DELETE CASCADE,
    risk_level                  automation_risk NOT NULL,
    automatable_tasks           TEXT,
    resilient_human_skills      TEXT,
    future_proof_recommendation TEXT
);

CREATE TABLE IF NOT EXISTS career_work_life_balance (
    career_id           UUID PRIMARY KEY REFERENCES careers(career_id) ON DELETE CASCADE,
    rating               wlb_rating NOT NULL,
    avg_weekly_hours     NUMERIC(4,1),
    flexibility          TEXT,
    shift_requirement    TEXT,
    travel_frequency     TEXT
);

CREATE TABLE IF NOT EXISTS career_remote_work (
    career_id   UUID PRIMARY KEY REFERENCES careers(career_id) ON DELETE CASCADE,
    potential   remote_potential NOT NULL
);

CREATE TABLE IF NOT EXISTS employment_opportunity_types (
    type_id     SERIAL PRIMARY KEY,
    sector      employer_sector NOT NULL,
    name        TEXT NOT NULL,
    UNIQUE (sector, name)
);

CREATE TABLE IF NOT EXISTS career_employment_opportunities (
    career_id   UUID NOT NULL REFERENCES careers(career_id) ON DELETE CASCADE,
    type_id     INT NOT NULL REFERENCES employment_opportunity_types(type_id),
    PRIMARY KEY (career_id, type_id)
);

CREATE TABLE IF NOT EXISTS career_progression_roles (
    id              SERIAL PRIMARY KEY,
    career_id       UUID NOT NULL REFERENCES careers(career_id) ON DELETE CASCADE,
    level           progression_level NOT NULL,
    role_title      TEXT NOT NULL,
    sequence_order  SMALLINT NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS riasec_types (
    riasec_id   SERIAL PRIMARY KEY,
    code        CHAR(1) NOT NULL UNIQUE,
    name        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS career_riasec (
    career_id   UUID NOT NULL REFERENCES careers(career_id) ON DELETE CASCADE,
    riasec_id   INT NOT NULL REFERENCES riasec_types(riasec_id),
    PRIMARY KEY (career_id, riasec_id)
);

CREATE TABLE IF NOT EXISTS mbti_types (
    mbti_id     SERIAL PRIMARY KEY,
    code        CHAR(4) NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS career_mbti (
    career_id   UUID NOT NULL REFERENCES careers(career_id) ON DELETE CASCADE,
    mbti_id     INT NOT NULL REFERENCES mbti_types(mbti_id),
    PRIMARY KEY (career_id, mbti_id)
);

CREATE TABLE IF NOT EXISTS core_strengths (
    strength_id SERIAL PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS career_core_strengths (
    career_id    UUID NOT NULL REFERENCES careers(career_id) ON DELETE CASCADE,
    strength_id  INT NOT NULL REFERENCES core_strengths(strength_id),
    PRIMARY KEY (career_id, strength_id)
);

CREATE TABLE IF NOT EXISTS subjects (
    subject_id  SERIAL PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS career_subjects (
    career_id   UUID NOT NULL REFERENCES careers(career_id) ON DELETE CASCADE,
    subject_id  INT NOT NULL REFERENCES subjects(subject_id),
    PRIMARY KEY (career_id, subject_id)
);

CREATE TABLE IF NOT EXISTS career_related_industries (
    career_id       UUID NOT NULL REFERENCES careers(career_id) ON DELETE CASCADE,
    industry_id     INT NOT NULL REFERENCES industries(industry_id),
    relation_type   industry_relation NOT NULL,
    PRIMARY KEY (career_id, industry_id, relation_type)
);

CREATE TABLE IF NOT EXISTS recruiters (
    recruiter_id    SERIAL PRIMARY KEY,
    name            TEXT NOT NULL UNIQUE,
    recruiter_type  TEXT NOT NULL CHECK (recruiter_type IN ('Government','PSU','Indian Company','Global Company','Startup'))
);

CREATE TABLE IF NOT EXISTS career_recruiters (
    career_id       UUID NOT NULL REFERENCES careers(career_id) ON DELETE CASCADE,
    recruiter_id    INT NOT NULL REFERENCES recruiters(recruiter_id),
    PRIMARY KEY (career_id, recruiter_id)
);

CREATE TABLE IF NOT EXISTS certifications (
    certification_id    SERIAL PRIMARY KEY,
    name                 TEXT NOT NULL UNIQUE,
    level                certification_level NOT NULL,
    issuing_body         TEXT
);

CREATE TABLE IF NOT EXISTS career_certifications (
    career_id           UUID NOT NULL REFERENCES careers(career_id) ON DELETE CASCADE,
    certification_id    INT NOT NULL REFERENCES certifications(certification_id),
    PRIMARY KEY (career_id, certification_id)
);

CREATE TABLE IF NOT EXISTS career_internships (
    id          SERIAL PRIMARY KEY,
    career_id   UUID NOT NULL REFERENCES careers(career_id) ON DELETE CASCADE,
    stage       internship_stage NOT NULL,
    description TEXT
);

CREATE TABLE IF NOT EXISTS learning_resources (
    resource_id     SERIAL PRIMARY KEY,
    resource_type   resource_type NOT NULL,
    title           TEXT NOT NULL,
    author_or_host  TEXT,
    url             TEXT
);

CREATE TABLE IF NOT EXISTS career_learning_resources (
    career_id       UUID NOT NULL REFERENCES careers(career_id) ON DELETE CASCADE,
    resource_id     INT NOT NULL REFERENCES learning_resources(resource_id),
    PRIMARY KEY (career_id, resource_id)
);

CREATE TABLE IF NOT EXISTS countries (
    country_id  SERIAL PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS career_international_opportunities (
    id                      SERIAL PRIMARY KEY,
    career_id               UUID NOT NULL REFERENCES careers(career_id) ON DELETE CASCADE,
    country_id              INT NOT NULL REFERENCES countries(country_id),
    skill_shortage_area     TEXT,
    licensing_requirement   TEXT,
    migration_pathway       TEXT,
    UNIQUE (career_id, country_id)
);

CREATE TABLE IF NOT EXISTS career_advantages (
    id          SERIAL PRIMARY KEY,
    career_id   UUID NOT NULL REFERENCES careers(career_id) ON DELETE CASCADE,
    advantage   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS career_challenges (
    id          SERIAL PRIMARY KEY,
    career_id   UUID NOT NULL REFERENCES careers(career_id) ON DELETE CASCADE,
    challenge   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS career_roadmap_steps (
    id              SERIAL PRIMARY KEY,
    career_id       UUID NOT NULL REFERENCES careers(career_id) ON DELETE CASCADE,
    stage           roadmap_stage NOT NULL,
    description     TEXT,
    sequence_order  SMALLINT NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS comparison_metrics (
    metric_id   SERIAL PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS career_comparison_ratings (
    career_id   UUID NOT NULL REFERENCES careers(career_id) ON DELETE CASCADE,
    metric_id   INT NOT NULL REFERENCES comparison_metrics(metric_id),
    rating      SMALLINT NOT NULL CHECK (rating BETWEEN 1 AND 5),
    PRIMARY KEY (career_id, metric_id)
);

CREATE INDEX IF NOT EXISTS idx_salary_india_career     ON career_salary_india(career_id);
CREATE INDEX IF NOT EXISTS idx_demand_current          ON career_demand(current_demand);
CREATE INDEX IF NOT EXISTS idx_demand_future           ON career_demand(future_demand);
CREATE INDEX IF NOT EXISTS idx_automation_risk_level   ON career_automation_risk(risk_level);
CREATE INDEX IF NOT EXISTS idx_wlb_rating              ON career_work_life_balance(rating);
CREATE INDEX IF NOT EXISTS idx_remote_potential        ON career_remote_work(potential);
CREATE INDEX IF NOT EXISTS idx_comparison_metric       ON career_comparison_ratings(metric_id, rating);

-- ----------------------------------------------------------------------------
-- APP TABLES (auth, profile, scholarships, saved items, scrape sources)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS users (
    id              SERIAL PRIMARY KEY,
    name            TEXT NOT NULL,
    email           TEXT UNIQUE NOT NULL,
    password_hash   TEXT NOT NULL,
    is_admin        BOOLEAN NOT NULL DEFAULT FALSE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS profiles (
    user_id             INT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    education_level     TEXT,
    state               TEXT,
    category            TEXT,
    gender              TEXT,
    income_bracket      INTEGER,
    interests           TEXT,
    stream              TEXT,
    board               TEXT,
    marks_band          TEXT,
    subjects            TEXT,
    has_disability      BOOLEAN NOT NULL DEFAULT FALSE,
    is_first_generation BOOLEAN NOT NULL DEFAULT FALSE,
    is_rural            BOOLEAN NOT NULL DEFAULT FALSE,
    is_minority         BOOLEAN NOT NULL DEFAULT FALSE,
    language_pref       TEXT NOT NULL DEFAULT 'en',
    riasec_codes        TEXT
);

CREATE TABLE IF NOT EXISTS scholarships (
    id              SERIAL PRIMARY KEY,
    name            TEXT NOT NULL,
    provider        TEXT,
    type            TEXT,
    description     TEXT,
    education_level TEXT,
    states          TEXT,
    categories      TEXT,
    gender          TEXT,
    income_ceiling  INTEGER,
    amount          TEXT,
    deadline        TEXT,
    apply_url       TEXT,
    documents       TEXT,
    source          TEXT NOT NULL DEFAULT 'manual',
    source_url      TEXT,
    last_synced_at  TEXT,
    requires_disability BOOLEAN NOT NULL DEFAULT FALSE,
    requires_minority   BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE TABLE IF NOT EXISTS sources (
    id              SERIAL PRIMARY KEY,
    name            TEXT NOT NULL,
    target_type     TEXT NOT NULL,
    url             TEXT NOT NULL,
    parser          TEXT NOT NULL DEFAULT 'generic_html_table',
    enabled         BOOLEAN NOT NULL DEFAULT TRUE,
    last_run_at     TEXT,
    last_status     TEXT,
    last_message    TEXT,
    created_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS saved_careers (
    user_id     INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    career_id   UUID NOT NULL REFERENCES careers(career_id) ON DELETE CASCADE,
    created_at  TEXT NOT NULL,
    PRIMARY KEY (user_id, career_id)
);

CREATE TABLE IF NOT EXISTS saved_scholarships (
    user_id         INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    scholarship_id  INT NOT NULL REFERENCES scholarships(id) ON DELETE CASCADE,
    status          TEXT DEFAULT 'saved',
    created_at      TEXT NOT NULL,
    PRIMARY KEY (user_id, scholarship_id)
);

CREATE TABLE IF NOT EXISTS checklist_items (
    id          SERIAL PRIMARY KEY,
    user_id     INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    item_type   TEXT NOT NULL,
    ref_id      TEXT,
    label       TEXT NOT NULL,
    done        BOOLEAN NOT NULL DEFAULT FALSE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (user_id, item_type, ref_id, label)
);

CREATE TABLE IF NOT EXISTS assistant_messages (
    id          SERIAL PRIMARY KEY,
    user_id     INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role        TEXT NOT NULL,
    content     TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_assistant_messages_user ON assistant_messages(user_id, id);

CREATE TABLE IF NOT EXISTS share_links (
    token       TEXT PRIMARY KEY,
    user_id     INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS exam_calendar (
    id               SERIAL PRIMARY KEY,
    exam_name        TEXT NOT NULL UNIQUE,
    exam_code        TEXT,
    typical_window   TEXT,
    typical_month    SMALLINT,
    next_cycle       TEXT,
    education_level  TEXT,
    streams          TEXT,
    clusters         TEXT,
    official_url     TEXT,
    notes            TEXT
);

CREATE TABLE IF NOT EXISTS career_institutes (
    id              SERIAL PRIMARY KEY,
    career_id       UUID NOT NULL REFERENCES careers(career_id) ON DELETE CASCADE,
    name            TEXT NOT NULL,
    kind            TEXT,
    entrance        TEXT,
    typical_fees    TEXT,
    notes           TEXT
);

CREATE TABLE IF NOT EXISTS related_careers (
    career_id          UUID NOT NULL REFERENCES careers(career_id) ON DELETE CASCADE,
    related_career_id  UUID NOT NULL REFERENCES careers(career_id) ON DELETE CASCADE,
    PRIMARY KEY (career_id, related_career_id)
);

CREATE TABLE IF NOT EXISTS app_meta (
    key     TEXT PRIMARY KEY,
    value   TEXT
);

CREATE INDEX IF NOT EXISTS idx_careers_verified ON careers(is_verified);
CREATE INDEX IF NOT EXISTS idx_exam_calendar_month ON exam_calendar(typical_month);
CREATE INDEX IF NOT EXISTS idx_career_institutes_career ON career_institutes(career_id);

-- Government job notifications, populated by the pathwise-mcp MCP server: an
-- AI client extracts these fields from an official PDF notification and
-- calls save_job_to_database, which writes here (see pathwise-mcp/server.py).
-- A single notification commonly advertises several distinct posts at once
-- (different department/pay level/vacancy split each) — those go in
-- gov_job_posts below rather than being flattened into one row here.
CREATE TABLE IF NOT EXISTS gov_job_notifications (
    id                      SERIAL PRIMARY KEY,
    job_title               TEXT NOT NULL,
    department              TEXT,
    total_vacancies         INTEGER,
    reservation_details     JSONB,
    nationality             TEXT,
    qualification           TEXT,
    age_limit               TEXT,
    age_relaxation          TEXT,
    -- Structured breakdown of age_relaxation for notifications where the
    -- rules span multiple clauses/sections (common — a base clause list plus
    -- a separately-referenced rule incorporated by reference). Array of
    -- objects, each e.g. {"source": "8.1(B)(i)", "category": "SC/ST/OBC",
    -- "relaxation": "up to 5 years", "cap": "..."}. Nullable — omit for
    -- notifications with a single simple relaxation rule.
    age_relaxation_details  JSONB,
    apply_start_date        TEXT,
    apply_end_date          TEXT,
    exam_date               TEXT,
    advertisement_number    TEXT,
    application_fee         TEXT,
    official_url            TEXT,
    local_pdf_path          TEXT,
    source                  TEXT NOT NULL DEFAULT 'mcp:gov-job-extractor',
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- Original regional-language text preserved alongside the English fields
    -- above (these PDFs are routinely bilingual). Keyed by ISO language code
    -- for any of the 22 Eighth Schedule languages, e.g.
    -- {"hi": {"job_title": "...", "department": "...", "qualification": "..."}}.
    -- See EIGHTH_SCHEDULE_LANGUAGES in pathwise-mcp/server.py for the code list.
    translations            JSONB,
    -- Exam scheme/syllabus, nullable. Shape: {"papers": [{"name": "...",
    -- "questions": 100, "marks": 200, "duration": "2:00 hours",
    -- "negative_marking": "...", "parts": [{"name": "...", "topics": [...]}]}],
    -- "language_note": "..."} — one entry per stage (e.g. keyed by
    -- "preliminary"/"main") when a notification has more than one.
    syllabus                JSONB,
    -- Search / display fields written by pathwise-mcp (kept here so a
    -- DROP SCHEMA + schema.sql rebuild does not lose the columns).
    commission              TEXT,
    state                   TEXT,
    exam_name               TEXT,
    exam_kind               TEXT,
    search_document         TEXT
);

CREATE TABLE IF NOT EXISTS gov_job_posts (
    id                      SERIAL PRIMARY KEY,
    notification_id         INT NOT NULL REFERENCES gov_job_notifications(id) ON DELETE CASCADE,
    post_name               TEXT NOT NULL,
    department              TEXT,
    pay_level               TEXT,
    total_vacancies         INTEGER,
    vacancies_breakdown     JSONB,
    qualification           TEXT,
    -- Same shape as gov_job_notifications.translations, scoped to this post's
    -- own fields (keys: post_name, department, qualification).
    translations            JSONB
);

CREATE INDEX IF NOT EXISTS idx_gov_job_posts_notification ON gov_job_posts(notification_id);

CREATE TABLE IF NOT EXISTS saved_gov_jobs (
    user_id         INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    notification_id INT NOT NULL REFERENCES gov_job_notifications(id) ON DELETE CASCADE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, notification_id)
);

-- ----------------------------------------------------------------------------
-- APP-FACING VIEW: flattens the normalized career tables into the shape the
-- Flask app's templates expect (one row per career, skills/exams aggregated).
-- career_category name doubles as the onboarding "interest cluster" key.
-- ----------------------------------------------------------------------------
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
LEFT JOIN career_remote_work rw           ON rw.career_id = c.career_id;

-- ============================================================================
-- USEFUL COMPOSITE VIEW: quick summary row per career for list/search pages
-- (kept from the master schema for future richer explorer/compare pages)
-- ============================================================================
CREATE OR REPLACE VIEW career_summary AS
SELECT
    c.career_id,
    c.career_code,
    c.career_name,
    cc.name AS category,
    i.name  AS primary_industry,
    d.current_demand,
    d.future_demand,
    ar.risk_level AS automation_risk,
    wlb.rating AS work_life_balance,
    rw.potential AS remote_work_potential,
    c.entrepreneurship_potential
FROM careers c
LEFT JOIN career_categories cc          ON cc.category_id = c.career_category_id
LEFT JOIN industries i                  ON i.industry_id = c.primary_industry_id
LEFT JOIN career_demand d               ON d.career_id = c.career_id
LEFT JOIN career_automation_risk ar     ON ar.career_id = c.career_id
LEFT JOIN career_work_life_balance wlb  ON wlb.career_id = c.career_id
LEFT JOIN career_remote_work rw         ON rw.career_id = c.career_id;
