import os
import json
import re
import secrets
import datetime
from functools import wraps

from flask import Flask, g, request, redirect, url_for, render_template, session, flash, jsonify, send_file
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

import db as dbmod
from seed_data import CAREERS, SCHOLARSHIPS, INTEREST_CLUSTERS
import scraper
from i18n import translate, normalize_lang
from matching import (
    STREAMS, BOARDS, MARKS_BANDS, SUBJECT_OPTIONS, SCHOLARSHIP_STATUSES,
    parse_list, parse_flexible_date, profile_interests, profile_subjects, profile_riasec,
    scholarship_matches_profile, scholarship_match_explanation,
    recommended_career_ids, recommended_career_rows, score_career,
    next_steps_for_profile, gov_job_is_open, gov_job_eligibility, is_national_job,
    RIASEC_QUESTIONS, score_riasec,
)
from gov_jobs import (
    EXAM_KINDS, annotate_job, distinct_commissions, fetch_gov_jobs, related_gov_jobs,
)
# assistant is imported lazily inside the /assistant routes so the app can start
# without the optional 'openai' package (see requirements.txt and AGENTS.md)

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-key-change-in-production")
app.config["MAX_CONTENT_LENGTH"] = 32 * 1024 * 1024  # 32MB, generous for a scanned notification PDF

# Drop folder for the sibling pathwise-mcp poller (see ../pathwise-mcp/INTEGRATING.md).
# Admin uploads land here; the MCP process copies to stored_pdfs/, extracts, and INSERTs.
# We detect a successful ingest by matching the original filename stem to local_pdf_path.
# Both projects must share a host (or these volumes) and the same DATABASE_URL.
GOV_JOB_UPLOAD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "pathwise-mcp", "tobepicked")

EDUCATION_LEVELS = ["Class 9-10", "Class 11-12", "Undergraduate", "Postgraduate", "Diploma"]
CATEGORIES = ["General", "OBC", "SC", "ST", "EWS", "Minority"]
INDIAN_STATES = [
    "Andhra Pradesh", "Arunachal Pradesh", "Assam", "Bihar", "Chhattisgarh",
    "Goa", "Gujarat", "Haryana", "Himachal Pradesh", "Jharkhand", "Karnataka",
    "Kerala", "Madhya Pradesh", "Maharashtra", "Manipur", "Meghalaya",
    "Mizoram", "Nagaland", "Odisha", "Punjab", "Rajasthan", "Sikkim",
    "Tamil Nadu", "Telangana", "Tripura", "Uttar Pradesh", "Uttarakhand",
    "West Bengal", "Andaman and Nicobar Islands", "Chandigarh",
    "Dadra and Nagar Haveli and Daman and Diu", "Delhi", "Jammu and Kashmir",
    "Ladakh", "Lakshadweep", "Puducherry", "Other",
]


# ----------------- DB HELPERS -----------------

def get_db():
    if "db" not in g:
        g.db = dbmod.Connection(dbmod.connect())
    return g.db


@app.teardown_appcontext
def close_db(exception=None):
    conn = g.pop("db", None)
    if conn is not None:
        if exception is None:
            conn.commit()
        else:
            conn.rollback()
        conn.close()


def init_db():
    fresh = dbmod.init_db()

    conn = dbmod.Connection(dbmod.connect())
    try:
        career_count = conn.execute("SELECT COUNT(*) AS n FROM careers").fetchone()["n"]
        if career_count < len(CAREERS):
            from seed_data import seed_careers
            seed_careers(conn, CAREERS)
            conn.commit()

        sch_count = conn.execute("SELECT COUNT(*) AS n FROM scholarships").fetchone()["n"]
        if sch_count == 0:
            from seed_data import seed_scholarships
            seed_scholarships(conn, SCHOLARSHIPS)
            conn.commit()

        from content_seed import seed_app_content
        seed_app_content(conn)
        conn.commit()
    finally:
        conn.close()

    return fresh


def now_iso():
    return datetime.datetime.utcnow().isoformat()


# ----------------- CAREER SCHEMA HELPERS -----------------
# The `careers` table is one of ~25 normalized tables (see schema.sql). These
# helpers flatten the admin form's simple field set back out across the
# category/demand/salary/automation-risk/skills/exams tables, and get-or-create
# lookup rows (categories, skills, exams) by name.

def upsert_lookup(db, table, id_col, name_col, name, extra=None):
    row = db.execute(f"SELECT {id_col} FROM {table} WHERE {name_col} = ?", (name,)).fetchone()
    if row:
        return row[id_col]
    cols = [name_col] + list((extra or {}).keys())
    vals = [name] + list((extra or {}).values())
    placeholders = ",".join(["?"] * len(cols))
    cur = db.execute(
        f"INSERT INTO {table} ({','.join(cols)}) VALUES ({placeholders}) RETURNING {id_col}",
        vals,
    )
    return cur.fetchone()[id_col]


def save_career_admin(db, career_id, values):
    """Create/update a career from the admin form's flat field set.

    values: dict with slug, name, cluster, description, demand, salary_min,
    salary_max, skills (comma-separated), ai_impact, education_path,
    exams (comma-separated).
    """
    category_id = upsert_lookup(db, "career_categories", "category_id", "name", values["cluster"]) \
        if values["cluster"] else None

    if career_id:
        db.execute(
            """UPDATE careers SET slug=?, career_name=?, career_category_id=?, description=?,
               min_education_qualification=?, updated_at=now() WHERE career_id=?""",
            (values["slug"], values["name"], category_id, values["description"],
             values["education_path"], career_id),
        )
    else:
        career_code = re.sub(r"[^A-Z0-9]+", "-", values["slug"].upper()).strip("-")
        cur = db.execute(
            """INSERT INTO careers (career_code, slug, career_name, career_category_id, description,
               min_education_qualification, source, last_synced_at)
               VALUES (?,?,?,?,?,?,'manual',?) RETURNING career_id""",
            (career_code, values["slug"], values["name"], category_id, values["description"],
             values["education_path"], now_iso()),
        )
        career_id = cur.fetchone()["career_id"]

    if values.get("demand"):
        db.execute(
            """INSERT INTO career_demand (career_id, current_demand, future_demand) VALUES (?,?,?)
               ON CONFLICT (career_id) DO UPDATE SET current_demand=EXCLUDED.current_demand,
                 future_demand=EXCLUDED.future_demand""",
            (career_id, values["demand"], values["demand"]),
        )

    if values.get("salary_min") is not None or values.get("salary_max") is not None:
        db.execute(
            """INSERT INTO career_salary_india (career_id, level, min_salary_inr, max_salary_inr)
               VALUES (?, 'Entry Level (0-3 Yrs)', ?, ?)
               ON CONFLICT (career_id, level) DO UPDATE SET min_salary_inr=EXCLUDED.min_salary_inr,
                 max_salary_inr=EXCLUDED.max_salary_inr""",
            (career_id, values.get("salary_min"), values.get("salary_max")),
        )

    if values.get("ai_impact"):
        db.execute(
            """INSERT INTO career_automation_risk (career_id, risk_level, future_proof_recommendation)
               VALUES (?, 'Moderate', ?)
               ON CONFLICT (career_id) DO UPDATE SET future_proof_recommendation=EXCLUDED.future_proof_recommendation""",
            (career_id, values["ai_impact"]),
        )

    db.execute(
        "UPDATE careers SET is_verified = ? WHERE career_id = ?",
        (bool(values.get("is_verified")), career_id),
    )

    db.execute("DELETE FROM career_skills WHERE career_id = ?", (career_id,))
    for name in parse_list(values.get("skills", "")):
        skill_id = upsert_lookup(db, "skills", "skill_id", "name", name, extra={"skill_type": "Technical"})
        db.execute(
            "INSERT INTO career_skills (career_id, skill_id) VALUES (?,?) ON CONFLICT DO NOTHING",
            (career_id, skill_id),
        )

    db.execute("DELETE FROM career_entrance_exams WHERE career_id = ?", (career_id,))
    for name in parse_list(values.get("exams", "")):
        exam_id = upsert_lookup(db, "entrance_exams", "exam_id", "name", name, extra={"exam_type": "National"})
        db.execute(
            "INSERT INTO career_entrance_exams (career_id, exam_id) VALUES (?,?) ON CONFLICT DO NOTHING",
            (career_id, exam_id),
        )

    return career_id


# ----------------- AUTH HELPERS -----------------

def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            flash("Please log in to continue.", "error")
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        user = current_user()
        if not user or not user["is_admin"]:
            flash("Admin access required.", "error")
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


def current_user():
    if not session.get("user_id"):
        return None
    db = get_db()
    return db.execute("SELECT * FROM users WHERE id = ?", (session["user_id"],)).fetchone()


def current_profile():
    if not session.get("user_id"):
        return None
    db = get_db()
    row = db.execute("SELECT * FROM profiles WHERE user_id = ?", (session["user_id"],)).fetchone()
    return row


def current_lang():
    if session.get("lang"):
        return normalize_lang(session["lang"])
    profile = current_profile()
    if profile and profile.get("language_pref"):
        return normalize_lang(profile["language_pref"])
    return "en"


@app.context_processor
def inject_user():
    lang = current_lang()
    return dict(
        current_user=current_user(),
        lang=lang,
        t=lambda key, default=None: translate(lang, key, default),
    )


# Matching helpers live in matching.py (shared with the assistant).


# ----------------- ROUTES: CORE -----------------

@app.route("/")
def index():
    if session.get("user_id"):
        return redirect(url_for("dashboard"))
    return render_template("index.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        if not name or not email or not password:
            flash("All fields are required.", "error")
            return render_template("register.html")
        if len(password) < 6:
            flash("Password must be at least 6 characters.", "error")
            return render_template("register.html")

        db = get_db()
        existing = db.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
        if existing:
            flash("An account with this email already exists.", "error")
            return render_template("register.html")

        cur = db.execute(
            "INSERT INTO users (name, email, password_hash, created_at) VALUES (?,?,?,?) RETURNING id",
            (name, email, generate_password_hash(password), now_iso()),
        )
        session["user_id"] = cur.fetchone()["id"]
        db.commit()
        flash("Welcome to PathWise! Let's find out more about you.", "success")
        return redirect(url_for("onboarding"))

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        db = get_db()
        user = db.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        if user and check_password_hash(user["password_hash"], password):
            session["user_id"] = user["id"]
            flash(f"Welcome back, {user['name']}!", "success")
            next_url = request.args.get("next") or url_for("dashboard")
            return redirect(next_url)
        flash("Invalid email or password.", "error")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for("index"))


# ----------------- ROUTES: ONBOARDING -----------------

def _profile_from_form():
    income_bracket = request.form.get("income_bracket") or None
    return dict(
        education_level=request.form.get("education_level"),
        state=request.form.get("state"),
        category=request.form.get("category"),
        gender=request.form.get("gender"),
        income_bracket=int(income_bracket) if income_bracket else None,
        interests=request.form.getlist("interests"),
        stream=request.form.get("stream") or None,
        board=request.form.get("board") or None,
        marks_band=request.form.get("marks_band") or None,
        subjects=request.form.getlist("subjects"),
        has_disability=request.form.get("has_disability") == "on",
        is_first_generation=request.form.get("is_first_generation") == "on",
        is_rural=request.form.get("is_rural") == "on",
        is_minority=request.form.get("is_minority") == "on",
    )


def upsert_profile(db, user_id, values, riasec_codes=None, language_pref=None):
    existing = db.execute("SELECT riasec_codes, language_pref FROM profiles WHERE user_id = ?", (user_id,)).fetchone()
    if riasec_codes is None:
        riasec_codes = existing["riasec_codes"] if existing else None
    if language_pref is None:
        language_pref = existing["language_pref"] if existing else current_lang()
    db.execute(
        """INSERT INTO profiles (user_id, education_level, state, category, gender,
           income_bracket, interests, stream, board, marks_band, subjects,
           has_disability, is_first_generation, is_rural, is_minority,
           language_pref, riasec_codes)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(user_id) DO UPDATE SET
             education_level=excluded.education_level, state=excluded.state,
             category=excluded.category, gender=excluded.gender,
             income_bracket=excluded.income_bracket, interests=excluded.interests,
             stream=excluded.stream, board=excluded.board, marks_band=excluded.marks_band,
             subjects=excluded.subjects, has_disability=excluded.has_disability,
             is_first_generation=excluded.is_first_generation, is_rural=excluded.is_rural,
             is_minority=excluded.is_minority, language_pref=excluded.language_pref,
             riasec_codes=excluded.riasec_codes""",
        (user_id, values["education_level"], values["state"], values["category"],
         values["gender"], values["income_bracket"], json.dumps(values["interests"]),
         values.get("stream"), values.get("board"), values.get("marks_band"),
         json.dumps(values.get("subjects") or []),
         values.get("has_disability") or False,
         values.get("is_first_generation") or False,
         values.get("is_rural") or False,
         values.get("is_minority") or False,
         language_pref, riasec_codes),
    )


@app.route("/onboarding", methods=["GET", "POST"])
@login_required
def onboarding():
    if request.method == "POST":
        db = get_db()
        upsert_profile(db, session["user_id"], _profile_from_form())
        db.commit()
        flash("Profile saved! Here's what we recommend for you.", "success")
        return redirect(url_for("dashboard"))

    profile = current_profile()
    return render_template(
        "onboarding.html", profile=profile, clusters=INTEREST_CLUSTERS,
        education_levels=EDUCATION_LEVELS, categories=CATEGORIES, states=INDIAN_STATES,
        streams=STREAMS, boards=BOARDS, marks_bands=MARKS_BANDS, subject_options=SUBJECT_OPTIONS,
        current_interests=profile_interests(profile),
        current_subjects=profile_subjects(profile),
    )


@app.route("/language", methods=["POST"])
def set_language():
    lang = normalize_lang(request.form.get("lang") or request.args.get("lang") or "en")
    session["lang"] = lang
    if session.get("user_id"):
        db = get_db()
        db.execute(
            "UPDATE profiles SET language_pref = ? WHERE user_id = ?",
            (lang, session["user_id"]),
        )
        db.commit()
    next_url = request.form.get("next") or request.referrer or url_for("index")
    return redirect(next_url)


# ----------------- ROUTES: CAREERS -----------------

def _career_sort_sql(sort):
    if sort == "salary":
        return "salary_max DESC NULLS LAST, name"
    if sort == "demand":
        return """CASE demand
            WHEN 'Very High' THEN 1 WHEN 'High' THEN 2 WHEN 'Medium' THEN 3
            ELSE 4 END, name"""
    return "is_verified DESC, name"


@app.route("/careers")
def careers_list():
    db = get_db()
    cluster_filter = request.args.get("cluster", "")
    q = (request.args.get("q") or "").strip()
    sort = request.args.get("sort", "name")
    show_all = request.args.get("all") == "1"

    clauses, params = [], []
    if not show_all and not q:
        clauses.append("is_verified = TRUE")
    if cluster_filter:
        clauses.append("cluster = ?")
        params.append(cluster_filter)
    if q:
        clauses.append("(name ILIKE ? OR description ILIKE ? OR COALESCE(skills,'') ILIKE ? OR COALESCE(exams,'') ILIKE ?)")
        like = f"%{q}%"
        params.extend([like, like, like, like])

    sql = "SELECT * FROM career_app_view"
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY " + _career_sort_sql(sort)
    rows = db.execute(sql, params).fetchall()

    saved_ids = set()
    profile = current_profile()
    recommended_ids = set(recommended_career_ids(profile, db)) if session.get("user_id") else set()
    if session.get("user_id"):
        saved_rows = db.execute("SELECT career_id FROM saved_careers WHERE user_id = ?", (session["user_id"],)).fetchall()
        saved_ids = {r["career_id"] for r in saved_rows}

    unverified_count = db.execute("SELECT COUNT(*) AS n FROM career_app_view WHERE is_verified = FALSE").fetchone()["n"]

    return render_template(
        "careers_list.html", careers=rows, clusters=INTEREST_CLUSTERS,
        active_cluster=cluster_filter, saved_ids=saved_ids, recommended_ids=recommended_ids,
        q=q, sort=sort, show_all=show_all, unverified_count=unverified_count,
    )


@app.route("/careers/compare")
def careers_compare():
    slugs = [s.strip() for s in (request.args.get("slugs") or "").split(",") if s.strip()][:3]
    db = get_db()
    careers = []
    for slug in slugs:
        row = db.execute("SELECT * FROM career_app_view WHERE slug = ?", (slug,)).fetchone()
        if row:
            careers.append(row)
    return render_template("career_compare.html", careers=careers)


@app.route("/careers/<slug>")
def career_detail(slug):
    db = get_db()
    career = db.execute("SELECT * FROM career_app_view WHERE slug = ?", (slug,)).fetchone()
    if not career:
        flash("Career not found.", "error")
        return redirect(url_for("careers_list"))

    is_saved = False
    profile = current_profile()
    if session.get("user_id"):
        row = db.execute(
            "SELECT 1 FROM saved_careers WHERE user_id = ? AND career_id = ?",
            (session["user_id"], career["career_id"]),
        ).fetchone()
        is_saved = row is not None

    institutes = db.execute(
        "SELECT * FROM career_institutes WHERE career_id = ? ORDER BY id", (career["career_id"],)
    ).fetchall()
    roadmap = db.execute(
        "SELECT * FROM career_roadmap_steps WHERE career_id = ? ORDER BY sequence_order, id",
        (career["career_id"],),
    ).fetchall()
    related = db.execute(
        """SELECT v.* FROM career_app_view v
           JOIN related_careers rc ON rc.related_career_id = v.career_id
           WHERE rc.career_id = ? ORDER BY v.is_verified DESC, v.name""",
        (career["career_id"],),
    ).fetchall()
    if not related:
        related = db.execute(
            """SELECT * FROM career_app_view
               WHERE cluster = ? AND career_id <> ? AND is_verified = TRUE
               ORDER BY name LIMIT 4""",
            (career["cluster"], career["career_id"]),
        ).fetchall()

    exam_names = parse_list(career.get("exams"))
    related_exams = []
    if exam_names:
        clauses = " OR ".join(["exam_name ILIKE ?"] * len(exam_names))
        related_exams = db.execute(
            f"SELECT * FROM exam_calendar WHERE {clauses} ORDER BY typical_month",
            [f"%{n}%" for n in exam_names],
        ).fetchall()

    related_scholarships = []
    if profile:
        all_sch = db.execute("SELECT * FROM scholarships ORDER BY deadline").fetchall()
        related_scholarships = [s for s in all_sch if scholarship_matches_profile(s, profile)][:4]
    else:
        related_scholarships = db.execute("SELECT * FROM scholarships ORDER BY deadline LIMIT 3").fetchall()

    related_jobs = [annotate_job(r) for r in related_gov_jobs(db, exam_names, limit=4)]

    match_reasons = []
    if profile:
        _, match_reasons = score_career(career, profile)

    return render_template(
        "career_detail.html", career=career, is_saved=is_saved, profile=profile,
        institutes=institutes, roadmap=roadmap, related=related,
        related_exams=related_exams, related_scholarships=related_scholarships,
        related_jobs=related_jobs, match_reasons=match_reasons,
    )


@app.route("/careers/<career_id>/toggle-save", methods=["POST"])
@login_required
def toggle_save_career(career_id):
    db = get_db()
    row = db.execute(
        "SELECT 1 FROM saved_careers WHERE user_id = ? AND career_id = ?",
        (session["user_id"], career_id),
    ).fetchone()
    if row:
        db.execute("DELETE FROM saved_careers WHERE user_id = ? AND career_id = ?", (session["user_id"], career_id))
        flash("Removed from your roadmap.", "success")
    else:
        db.execute(
            "INSERT INTO saved_careers (user_id, career_id, created_at) VALUES (?,?,?)",
            (session["user_id"], career_id, now_iso()),
        )
        _ensure_career_checklist(db, session["user_id"], career_id)
        flash("Added to your roadmap.", "success")
    db.commit()
    return redirect(request.referrer or url_for("careers_list"))


# ----------------- ROUTES: SCHOLARSHIPS -----------------

@app.route("/scholarships")
def scholarships_list():
    db = get_db()
    type_filter = request.args.get("type", "")
    show_matches_only = request.args.get("matches") == "1"
    q = (request.args.get("q") or "").strip()

    clauses, params = [], []
    if type_filter:
        clauses.append("type = ?")
        params.append(type_filter)
    if q:
        clauses.append("(name ILIKE ? OR provider ILIKE ? OR COALESCE(description,'') ILIKE ?)")
        like = f"%{q}%"
        params.extend([like, like, like])
    sql = "SELECT * FROM scholarships"
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY deadline"
    rows = db.execute(sql, params).fetchall()

    profile = current_profile()
    matched_ids = set()
    explanations = {}
    if profile:
        for r in rows:
            expl = scholarship_match_explanation(r, profile)
            explanations[r["id"]] = expl
            if expl["matched"]:
                matched_ids.add(r["id"])
        if show_matches_only:
            rows = [r for r in rows if r["id"] in matched_ids]

    saved_ids = set()
    if session.get("user_id"):
        saved_rows = db.execute("SELECT scholarship_id FROM saved_scholarships WHERE user_id = ?", (session["user_id"],)).fetchall()
        saved_ids = {r["scholarship_id"] for r in saved_rows}

    types = [r["type"] for r in db.execute("SELECT DISTINCT type FROM scholarships ORDER BY type").fetchall()]

    return render_template(
        "scholarships_list.html", scholarships=rows, types=types, active_type=type_filter,
        matched_ids=matched_ids, saved_ids=saved_ids, has_profile=profile is not None,
        show_matches_only=show_matches_only, q=q, explanations=explanations,
    )


@app.route("/scholarships/<int:scholarship_id>")
def scholarship_detail(scholarship_id):
    db = get_db()
    sch = db.execute("SELECT * FROM scholarships WHERE id = ?", (scholarship_id,)).fetchone()
    if not sch:
        flash("Scholarship not found.", "error")
        return redirect(url_for("scholarships_list"))

    profile = current_profile()
    explanation = scholarship_match_explanation(sch, profile) if profile else None
    is_match = explanation["matched"] if explanation else None

    is_saved = False
    saved_status = None
    if session.get("user_id"):
        row = db.execute(
            "SELECT status FROM saved_scholarships WHERE user_id = ? AND scholarship_id = ?",
            (session["user_id"], scholarship_id),
        ).fetchone()
        is_saved = row is not None
        saved_status = row["status"] if row else None

    return render_template(
        "scholarship_detail.html", sch=sch, is_match=is_match, is_saved=is_saved,
        explanation=explanation, saved_status=saved_status, statuses=SCHOLARSHIP_STATUSES,
    )


@app.route("/scholarships/<int:scholarship_id>/toggle-save", methods=["POST"])
@login_required
def toggle_save_scholarship(scholarship_id):
    db = get_db()
    row = db.execute(
        "SELECT 1 FROM saved_scholarships WHERE user_id = ? AND scholarship_id = ?",
        (session["user_id"], scholarship_id),
    ).fetchone()
    if row:
        db.execute("DELETE FROM saved_scholarships WHERE user_id = ? AND scholarship_id = ?", (session["user_id"], scholarship_id))
        flash("Removed from your roadmap.", "success")
    else:
        db.execute(
            "INSERT INTO saved_scholarships (user_id, scholarship_id, created_at) VALUES (?,?,?)",
            (session["user_id"], scholarship_id, now_iso()),
        )
        sch = db.execute("SELECT * FROM scholarships WHERE id = ?", (scholarship_id,)).fetchone()
        if sch:
            _ensure_scholarship_checklist(db, session["user_id"], sch)
        flash("Added to your roadmap.", "success")
    db.commit()
    return redirect(request.referrer or url_for("scholarships_list"))


# ----------------- ROUTES: GOVERNMENT JOB NOTIFICATIONS -----------------
# Populated out-of-band by pathwise-mcp (shared Postgres + tobepicked/).
# This app SELECTs only — see gov_jobs.py and ../pathwise-mcp/INTEGRATING.md.

@app.route("/gov-jobs")
def gov_jobs_list():
    db = get_db()
    q = (request.args.get("q") or "").strip()
    commission = (request.args.get("commission") or "").strip()
    state = (request.args.get("state") or "").strip()
    exam_kind = (request.args.get("exam_kind") or "").strip()
    status = request.args.get("status") or "all"

    rows = fetch_gov_jobs(db, q=q, commission=commission, state=state, exam_kind=exam_kind)

    today = datetime.date.today()
    annotated = []
    for r in rows:
        open_flag = gov_job_is_open(r, today)
        if status == "open" and open_flag is False:
            continue
        if status == "closed" and open_flag is not False:
            continue
        item = annotate_job(r)
        item["is_open"] = open_flag
        item["is_national"] = is_national_job(r)
        annotated.append(item)

    saved_ids = set()
    if session.get("user_id"):
        saved_rows = db.execute(
            "SELECT notification_id FROM saved_gov_jobs WHERE user_id = ?", (session["user_id"],)
        ).fetchall()
        saved_ids = {r["notification_id"] for r in saved_rows}

    return render_template(
        "gov_jobs_list.html", jobs=annotated, q=q, commission=commission, state=state,
        exam_kind=exam_kind, exam_kinds=EXAM_KINDS, status=status,
        saved_ids=saved_ids, commissions=distinct_commissions(db),
    )


@app.route("/gov-jobs/<int:job_id>")
def gov_job_detail(job_id):
    db = get_db()
    row = db.execute("SELECT * FROM gov_job_notifications WHERE id = ?", (job_id,)).fetchone()
    if not row:
        flash("Job notification not found.", "error")
        return redirect(url_for("gov_jobs_list"))
    posts = db.execute("SELECT * FROM gov_job_posts WHERE notification_id = ? ORDER BY id", (job_id,)).fetchall()
    job = annotate_job(row)
    job["post_count"] = len(posts)
    if job["exam_kind"] in ("combined_exam", "departmental_exam") and posts:
        job["posts_badge"] = f"{len(posts)} cadres"
    elif len(posts) > 1:
        job["posts_badge"] = f"{len(posts)} posts"
    profile = current_profile()
    eligibility = gov_job_eligibility(row, profile)
    is_saved = False
    if session.get("user_id"):
        is_saved = db.execute(
            "SELECT 1 FROM saved_gov_jobs WHERE user_id = ? AND notification_id = ?",
            (session["user_id"], job_id),
        ).fetchone() is not None
    hi_tr = None
    translations = job.get("translations")
    if current_lang() == "hi" and isinstance(translations, dict):
        hi_tr = translations.get("hi") or translations.get("HI")
    return render_template(
        "gov_job_detail.html", job=job, posts=posts, is_saved=is_saved,
        eligibility=eligibility, is_open=gov_job_is_open(row), hi_tr=hi_tr,
        is_national=is_national_job(row),
    )


@app.route("/gov-jobs/<int:job_id>/toggle-save", methods=["POST"])
@login_required
def toggle_save_gov_job(job_id):
    db = get_db()
    row = db.execute(
        "SELECT 1 FROM saved_gov_jobs WHERE user_id = ? AND notification_id = ?",
        (session["user_id"], job_id),
    ).fetchone()
    if row:
        db.execute(
            "DELETE FROM saved_gov_jobs WHERE user_id = ? AND notification_id = ?",
            (session["user_id"], job_id),
        )
        flash("Removed from your roadmap.", "success")
    else:
        db.execute(
            "INSERT INTO saved_gov_jobs (user_id, notification_id) VALUES (?,?) ON CONFLICT DO NOTHING",
            (session["user_id"], job_id),
        )
        flash("Added to your roadmap.", "success")
    db.commit()
    return redirect(request.referrer or url_for("gov_jobs_list"))


def _resolve_gov_job_pdf(raw):
    """Accept absolute paths or MCP-relative stored_pdfs/<name>."""
    if not raw:
        return None
    if os.path.isfile(raw):
        return raw
    name = os.path.basename(raw)
    here = os.path.dirname(os.path.abspath(__file__))
    roots = [
        os.environ.get("GOV_JOB_PDF_DIR") or "",
        os.path.join(here, "..", "pathwise-mcp", "stored_pdfs"),
        os.path.join(here, "stored_pdfs"),
    ]
    for root in roots:
        if not root:
            continue
        cand = os.path.abspath(os.path.join(root, name))
        if os.path.isfile(cand):
            return cand
    return None


@app.route("/gov-jobs/<int:job_id>/pdf")
def gov_job_pdf(job_id):
    db = get_db()
    job = db.execute("SELECT local_pdf_path FROM gov_job_notifications WHERE id = ?", (job_id,)).fetchone()
    path = _resolve_gov_job_pdf(job["local_pdf_path"] if job else None)
    if not path:
        flash("PDF not available for this notification.", "error")
        return redirect(url_for("gov_jobs_list"))
    return send_file(path)


# ----------------- ROUTES: ADMIN -----------------

CAREER_FIELDS = ["slug", "name", "cluster", "description", "demand", "salary_min",
                  "salary_max", "skills", "ai_impact", "education_path", "exams"]


def _ensure_scholarship_checklist(db, user_id, sch):
    for doc in parse_list(sch.get("documents")):
        db.execute(
            """INSERT INTO checklist_items (user_id, item_type, ref_id, label)
               VALUES (?,?,?,?) ON CONFLICT (user_id, item_type, ref_id, label) DO NOTHING""",
            (user_id, "scholarship_doc", str(sch["id"]), doc),
        )


def _ensure_career_checklist(db, user_id, career_id):
    steps = db.execute(
        "SELECT description FROM career_roadmap_steps WHERE career_id = ? ORDER BY sequence_order",
        (career_id,),
    ).fetchall()
    for step in steps:
        if not step["description"]:
            continue
        db.execute(
            """INSERT INTO checklist_items (user_id, item_type, ref_id, label)
               VALUES (?,?,?,?) ON CONFLICT (user_id, item_type, ref_id, label) DO NOTHING""",
            (user_id, "career_step", str(career_id), step["description"]),
        )
SCHOLARSHIP_FIELDS = ["name", "provider", "type", "description", "education_level", "states",
                       "categories", "gender", "income_ceiling", "amount", "deadline",
                       "apply_url", "documents"]


@app.route("/admin")
@admin_required
def admin_home():
    db = get_db()
    counts = {
        "careers": db.execute("SELECT COUNT(*) AS n FROM careers").fetchone()["n"],
        "scholarships": db.execute("SELECT COUNT(*) AS n FROM scholarships").fetchone()["n"],
        "sources": db.execute("SELECT COUNT(*) AS n FROM sources").fetchone()["n"],
        "gov_job_notifications": db.execute("SELECT COUNT(*) AS n FROM gov_job_notifications").fetchone()["n"],
    }
    return render_template("admin/home.html", counts=counts)


@app.route("/admin/careers")
@admin_required
def admin_careers_list():
    db = get_db()
    rows = db.execute("SELECT * FROM career_app_view ORDER BY name").fetchall()
    return render_template("admin/careers_list.html", careers=rows)


@app.route("/admin/careers/new", methods=["GET", "POST"])
@admin_required
def admin_career_new():
    if request.method == "POST":
        db = get_db()
        values = {f: request.form.get(f, "").strip() for f in CAREER_FIELDS}
        values["salary_min"] = int(values["salary_min"]) if values["salary_min"] else None
        values["salary_max"] = int(values["salary_max"]) if values["salary_max"] else None
        values["is_verified"] = request.form.get("is_verified") == "on"
        save_career_admin(db, None, values)
        db.commit()
        flash("Career added.", "success")
        return redirect(url_for("admin_careers_list"))
    return render_template("admin/career_form.html", career=None, clusters=INTEREST_CLUSTERS)


@app.route("/admin/careers/<career_id>/edit", methods=["GET", "POST"])
@admin_required
def admin_career_edit(career_id):
    db = get_db()
    career = db.execute("SELECT * FROM career_app_view WHERE career_id = ?", (career_id,)).fetchone()
    if not career:
        flash("Career not found.", "error")
        return redirect(url_for("admin_careers_list"))

    if request.method == "POST":
        values = {f: request.form.get(f, "").strip() for f in CAREER_FIELDS}
        values["salary_min"] = int(values["salary_min"]) if values["salary_min"] else None
        values["salary_max"] = int(values["salary_max"]) if values["salary_max"] else None
        values["is_verified"] = request.form.get("is_verified") == "on"
        save_career_admin(db, career_id, values)
        db.commit()
        flash("Career updated.", "success")
        return redirect(url_for("admin_careers_list"))
    return render_template("admin/career_form.html", career=career, clusters=INTEREST_CLUSTERS)


@app.route("/admin/careers/<career_id>/delete", methods=["POST"])
@admin_required
def admin_career_delete(career_id):
    db = get_db()
    db.execute("DELETE FROM careers WHERE career_id = ?", (career_id,))
    db.commit()
    flash("Career deleted.", "success")
    return redirect(url_for("admin_careers_list"))


@app.route("/admin/scholarships")
@admin_required
def admin_scholarships_list():
    db = get_db()
    rows = db.execute("SELECT * FROM scholarships ORDER BY deadline").fetchall()
    return render_template("admin/scholarships_list.html", scholarships=rows)


@app.route("/admin/scholarships/new", methods=["GET", "POST"])
@admin_required
def admin_scholarship_new():
    if request.method == "POST":
        db = get_db()
        values = {f: request.form.get(f, "").strip() for f in SCHOLARSHIP_FIELDS}
        values["income_ceiling"] = int(values["income_ceiling"]) if values["income_ceiling"] else None
        db.execute(
            """INSERT INTO scholarships (name, provider, type, description, education_level,
               states, categories, gender, income_ceiling, amount, deadline, apply_url,
               documents, source, last_synced_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,'manual',?)""",
            (values["name"], values["provider"], values["type"], values["description"],
             values["education_level"], values["states"], values["categories"], values["gender"],
             values["income_ceiling"], values["amount"], values["deadline"], values["apply_url"],
             values["documents"], now_iso()),
        )
        db.commit()
        flash("Scholarship added.", "success")
        return redirect(url_for("admin_scholarships_list"))
    return render_template(
        "admin/scholarship_form.html", sch=None, education_levels=EDUCATION_LEVELS,
        categories=CATEGORIES, states=INDIAN_STATES,
    )


@app.route("/admin/scholarships/<int:scholarship_id>/edit", methods=["GET", "POST"])
@admin_required
def admin_scholarship_edit(scholarship_id):
    db = get_db()
    sch = db.execute("SELECT * FROM scholarships WHERE id = ?", (scholarship_id,)).fetchone()
    if not sch:
        flash("Scholarship not found.", "error")
        return redirect(url_for("admin_scholarships_list"))

    if request.method == "POST":
        values = {f: request.form.get(f, "").strip() for f in SCHOLARSHIP_FIELDS}
        values["income_ceiling"] = int(values["income_ceiling"]) if values["income_ceiling"] else None
        db.execute(
            """UPDATE scholarships SET name=?, provider=?, type=?, description=?, education_level=?,
               states=?, categories=?, gender=?, income_ceiling=?, amount=?, deadline=?,
               apply_url=?, documents=? WHERE id=?""",
            (values["name"], values["provider"], values["type"], values["description"],
             values["education_level"], values["states"], values["categories"], values["gender"],
             values["income_ceiling"], values["amount"], values["deadline"], values["apply_url"],
             values["documents"], scholarship_id),
        )
        db.commit()
        flash("Scholarship updated.", "success")
        return redirect(url_for("admin_scholarships_list"))
    return render_template(
        "admin/scholarship_form.html", sch=sch, education_levels=EDUCATION_LEVELS,
        categories=CATEGORIES, states=INDIAN_STATES,
    )


@app.route("/admin/scholarships/<int:scholarship_id>/delete", methods=["POST"])
@admin_required
def admin_scholarship_delete(scholarship_id):
    db = get_db()
    db.execute("DELETE FROM scholarships WHERE id = ?", (scholarship_id,))
    db.commit()
    flash("Scholarship deleted.", "success")
    return redirect(url_for("admin_scholarships_list"))


@app.route("/admin/sources")
@admin_required
def admin_sources_list():
    db = get_db()
    rows = db.execute("SELECT * FROM sources ORDER BY name").fetchall()
    return render_template("admin/sources_list.html", sources=rows, parsers=list(scraper.PARSERS.keys()))


@app.route("/admin/sources/new", methods=["POST"])
@admin_required
def admin_source_new():
    db = get_db()
    name = request.form.get("name", "").strip()
    target_type = request.form.get("target_type", "scholarship")
    url = request.form.get("url", "").strip()
    parser = request.form.get("parser", "generic_html_table")
    if not name or not url:
        flash("Name and URL are required.", "error")
        return redirect(url_for("admin_sources_list"))
    db.execute(
        "INSERT INTO sources (name, target_type, url, parser, enabled, created_at) VALUES (?,?,?,?,TRUE,?)",
        (name, target_type, url, parser, now_iso()),
    )
    db.commit()
    flash("Source added. Use \"Run now\" to fetch it.", "success")
    return redirect(url_for("admin_sources_list"))


@app.route("/admin/sources/<int:source_id>/run", methods=["POST"])
@admin_required
def admin_source_run(source_id):
    db = get_db()
    source = db.execute("SELECT * FROM sources WHERE id = ?", (source_id,)).fetchone()
    if not source:
        flash("Source not found.", "error")
        return redirect(url_for("admin_sources_list"))

    status, message = scraper.run_source(db, source)
    db.execute(
        "UPDATE sources SET last_run_at=?, last_status=?, last_message=? WHERE id=?",
        (now_iso(), status, message, source_id),
    )
    db.commit()
    flash(message, "success" if status == "success" else "error")
    return redirect(url_for("admin_sources_list"))


@app.route("/admin/sources/<int:source_id>/delete", methods=["POST"])
@admin_required
def admin_source_delete(source_id):
    db = get_db()
    db.execute("DELETE FROM sources WHERE id = ?", (source_id,))
    db.commit()
    flash("Source deleted.", "success")
    return redirect(url_for("admin_sources_list"))


def _ingest_match_stems(local_pdf_path):
    """Stems MCP may have stored for an uploaded filename."""
    if not local_pdf_path:
        return []
    base = os.path.basename(local_pdf_path)
    if base.lower().endswith(".pdf"):
        base = base[:-4]
    stems = [base]
    if "_" in base:
        cand, suf = base.rsplit("_", 1)
        if suf.isdigit():
            stems.append(cand)
    return stems


@app.route("/admin/gov-jobs")
@admin_required
def admin_gov_jobs_list():
    db = get_db()
    try:
        rows = db.execute(
            "SELECT id, job_title, exam_name, commission, exam_kind, local_pdf_path, created_at "
            "FROM gov_job_notifications ORDER BY created_at DESC"
        ).fetchall()
    except Exception:
        db.rollback()
        rows = db.execute(
            "SELECT id, job_title, local_pdf_path, created_at "
            "FROM gov_job_notifications ORDER BY created_at DESC"
        ).fetchall()
    processed_count = len(rows)
    recent = [annotate_job(r) for r in rows[:40]]

    # MCP stores stored_pdfs/{stem}_{mtime_ns}.pdf; also match the bare stem.
    ingested = {}
    for r in rows:
        match = {
            "id": r["id"],
            "job_title": r["exam_name"] or r["job_title"],
            "created_at": str(r["created_at"])[:19],
        }
        for stem in _ingest_match_stems(r["local_pdf_path"]):
            ingested.setdefault(stem, []).append(match)

    pending = []
    mcp_running_hint = os.path.isdir(GOV_JOB_UPLOAD_DIR)
    if mcp_running_hint:
        for name in sorted(os.listdir(GOV_JOB_UPLOAD_DIR)):
            path = os.path.join(GOV_JOB_UPLOAD_DIR, name)
            if os.path.isfile(path):
                stem = os.path.splitext(name)[0]
                matches = ingested.get(stem, [])
                size = os.path.getsize(path)
                pending.append({
                    "name": name,
                    "size": size,
                    "placeholder": size == 0,
                    "status": "processed" if matches else "pending",
                    "matches": matches,
                })
    return render_template(
        "admin/gov_job_uploads.html",
        pending=pending,
        processed_count=processed_count,
        recent=recent,
    )


@app.route("/admin/gov-jobs/upload", methods=["POST"])
@admin_required
def admin_gov_job_upload():
    file = request.files.get("pdf")
    if not file or not file.filename:
        flash("Choose a PDF file to upload.", "error")
        return redirect(url_for("admin_gov_jobs_list"))

    filename = secure_filename(file.filename)
    if not filename.lower().endswith(".pdf"):
        flash("Only PDF files are accepted.", "error")
        return redirect(url_for("admin_gov_jobs_list"))

    os.makedirs(GOV_JOB_UPLOAD_DIR, exist_ok=True)
    dest = os.path.join(GOV_JOB_UPLOAD_DIR, filename)
    if os.path.exists(dest):
        stem, ext = os.path.splitext(filename)
        dest = os.path.join(GOV_JOB_UPLOAD_DIR, f"{stem}_{now_iso().replace(':', '').replace('-', '')}{ext}")
    file.save(dest)

    flash(
        f'"{filename}" queued in tobepicked/. Keep pathwise-mcp running — the poller extracts it '
        "into the shared database within a few seconds.",
        "success",
    )
    return redirect(url_for("admin_gov_jobs_list"))


@app.route("/admin/gov-jobs/pending/<path:filename>/delete", methods=["POST"])
@admin_required
def admin_gov_job_pending_delete(filename):
    filename = secure_filename(filename)
    path = os.path.join(GOV_JOB_UPLOAD_DIR, filename)
    if os.path.isfile(path) and os.path.dirname(os.path.abspath(path)) == os.path.abspath(GOV_JOB_UPLOAD_DIR):
        os.remove(path)
        flash("Pending upload removed.", "success")
    else:
        flash("File not found.", "error")
    return redirect(url_for("admin_gov_jobs_list"))


# ----------------- ROUTES: DASHBOARD -----------------

def _dashboard_payload(db, user_id, profile):
    saved_careers = db.execute(
        """SELECT v.* FROM career_app_view v
           JOIN saved_careers sc ON v.career_id = sc.career_id
           WHERE sc.user_id = ? ORDER BY v.name""",
        (user_id,),
    ).fetchall()

    saved_scholarships = db.execute(
        """SELECT scholarships.*, saved_scholarships.status AS save_status
           FROM scholarships
           JOIN saved_scholarships ON scholarships.id = saved_scholarships.scholarship_id
           WHERE saved_scholarships.user_id = ? ORDER BY scholarships.deadline""",
        (user_id,),
    ).fetchall()

    saved_jobs = [
        annotate_job(r)
        for r in db.execute(
            """SELECT n.* FROM gov_job_notifications n
               JOIN saved_gov_jobs sg ON sg.notification_id = n.id
               WHERE sg.user_id = ? ORDER BY n.apply_end_date""",
            (user_id,),
        ).fetchall()
    ]

    recommended_careers = recommended_career_rows(profile, db, limit=6) if profile else []
    matched_scholarships = []
    next_steps = None
    if profile:
        all_scholarships = db.execute("SELECT * FROM scholarships ORDER BY deadline").fetchall()
        matched_scholarships = [s for s in all_scholarships if scholarship_matches_profile(s, profile)][:6]
        next_steps = next_steps_for_profile(profile, current_lang())

    checklist = db.execute(
        "SELECT * FROM checklist_items WHERE user_id = ? ORDER BY done, id",
        (user_id,),
    ).fetchall()

    today = datetime.date.today()
    deadlines = []
    for s in saved_scholarships:
        d = parse_flexible_date(s.get("deadline"))
        if d:
            deadlines.append({"kind": "scholarship", "name": s["name"], "date": d,
                              "href": url_for("scholarship_detail", scholarship_id=s["id"]),
                              "closed": d < today})
    for j in saved_jobs:
        d = parse_flexible_date(j.get("apply_end_date"))
        if d:
            deadlines.append({"kind": "gov_job", "name": j.get("display_title") or j.get("exam_name") or j["job_title"],
                              "date": d, "href": url_for("gov_job_detail", job_id=j["id"]),
                              "closed": d < today})
    if profile:
        for s in matched_scholarships:
            d = parse_flexible_date(s.get("deadline"))
            if d and d >= today:
                deadlines.append({"kind": "scholarship", "name": s["name"], "date": d,
                                  "href": url_for("scholarship_detail", scholarship_id=s["id"]),
                                  "closed": False})
    # unique by name+date
    seen = set()
    unique = []
    for item in sorted(deadlines, key=lambda x: x["date"]):
        key = (item["name"], item["date"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    deadlines = unique[:8]

    share = db.execute("SELECT token FROM share_links WHERE user_id = ?", (user_id,)).fetchone()

    return dict(
        profile=profile, saved_careers=saved_careers, saved_scholarships=saved_scholarships,
        saved_jobs=saved_jobs, recommended_careers=recommended_careers,
        matched_scholarships=matched_scholarships, today=today.isoformat(),
        next_steps=next_steps, checklist=checklist, deadlines=deadlines,
        share_token=share["token"] if share else None, statuses=SCHOLARSHIP_STATUSES,
    )


@app.route("/dashboard")
@login_required
def dashboard():
    db = get_db()
    payload = _dashboard_payload(db, session["user_id"], current_profile())
    return render_template("dashboard.html", readonly=False, share_user=current_user(), **payload)


# ----------------- ROUTES: EXAMS, QUIZ, SHARE, CHECKLIST -----------------

@app.route("/exams")
def exams_calendar():
    db = get_db()
    stream = request.args.get("stream", "")
    edu = request.args.get("education", "")
    rows = db.execute("SELECT * FROM exam_calendar ORDER BY typical_month NULLS LAST, exam_name").fetchall()
    if stream:
        rows = [r for r in rows if not r["streams"] or stream in parse_list(r["streams"]) or "all" in parse_list(r["streams"])]
    if edu:
        rows = [r for r in rows if not r["education_level"] or edu in (r["education_level"] or "")]
    profile = current_profile()
    return render_template(
        "exams.html", exams=rows, stream=stream, education=edu,
        streams=STREAMS, education_levels=EDUCATION_LEVELS, profile=profile,
    )


@app.route("/quiz", methods=["GET", "POST"])
@login_required
def interest_quiz():
    profile = current_profile()
    if request.method == "POST":
        answers = {qid: request.form.get(qid) for qid, _l, _en, _hi in RIASEC_QUESTIONS}
        top, tallies = score_riasec(answers)
        db = get_db()
        if profile:
            db.execute(
                "UPDATE profiles SET riasec_codes = ? WHERE user_id = ?",
                (json.dumps(top), session["user_id"]),
            )
        else:
            upsert_profile(db, session["user_id"], {
                "education_level": None, "state": None, "category": None, "gender": None,
                "income_bracket": None, "interests": [], "subjects": [],
            }, riasec_codes=json.dumps(top))
        db.commit()
        flash("Quiz saved. Careers will now rank with your interest type.", "success")
        return redirect(url_for("dashboard"))
    return render_template(
        "quiz.html", questions=RIASEC_QUESTIONS, profile=profile,
        current_codes=profile_riasec(profile),
    )


@app.route("/dashboard/share", methods=["POST"])
@login_required
def dashboard_share():
    db = get_db()
    existing = db.execute("SELECT token FROM share_links WHERE user_id = ?", (session["user_id"],)).fetchone()
    if existing:
        token = existing["token"]
    else:
        token = secrets.token_urlsafe(16)
        db.execute("INSERT INTO share_links (token, user_id) VALUES (?,?)", (token, session["user_id"]))
        db.commit()
    flash("Share link created. Anyone with the link can view (not edit) your roadmap.", "success")
    return redirect(url_for("dashboard"))


@app.route("/share/<token>")
def shared_roadmap(token):
    db = get_db()
    link = db.execute("SELECT * FROM share_links WHERE token = ?", (token,)).fetchone()
    if not link:
        flash("This share link is invalid or has been removed.", "error")
        return redirect(url_for("index"))
    user = db.execute("SELECT * FROM users WHERE id = ?", (link["user_id"],)).fetchone()
    profile = db.execute("SELECT * FROM profiles WHERE user_id = ?", (link["user_id"],)).fetchone()
    payload = _dashboard_payload(db, link["user_id"], profile)
    return render_template("dashboard.html", readonly=True, share_user=user, **payload)


@app.route("/checklist/<int:item_id>/toggle", methods=["POST"])
@login_required
def toggle_checklist(item_id):
    db = get_db()
    row = db.execute(
        "SELECT * FROM checklist_items WHERE id = ? AND user_id = ?",
        (item_id, session["user_id"]),
    ).fetchone()
    if row:
        db.execute("UPDATE checklist_items SET done = ? WHERE id = ?", (not row["done"], item_id))
        db.commit()
    return redirect(request.referrer or url_for("dashboard"))


@app.route("/scholarships/<int:scholarship_id>/status", methods=["POST"])
@login_required
def set_scholarship_status(scholarship_id):
    status = request.form.get("status") or "saved"
    allowed = {s[0] for s in SCHOLARSHIP_STATUSES}
    if status not in allowed:
        status = "saved"
    db = get_db()
    db.execute(
        "UPDATE saved_scholarships SET status = ? WHERE user_id = ? AND scholarship_id = ?",
        (status, session["user_id"], scholarship_id),
    )
    db.commit()
    return redirect(request.referrer or url_for("dashboard"))


# ----------------- ROUTES: ASSISTANT -----------------

def _load_assistant_history(db, user_id):
    rows = db.execute(
        """SELECT role, content FROM assistant_messages
           WHERE user_id = ? AND role IN ('user', 'assistant')
           ORDER BY id DESC LIMIT 12""",
        (user_id,),
    ).fetchall()
    return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]


def _save_assistant_turn(db, user_id, user_message, reply):
    db.execute(
        "INSERT INTO assistant_messages (user_id, role, content) VALUES (?,?,?)",
        (user_id, "user", user_message),
    )
    db.execute(
        "INSERT INTO assistant_messages (user_id, role, content) VALUES (?,?,?)",
        (user_id, "assistant", reply or ""),
    )
    # keep last ~40 rows so the table does not grow forever
    db.execute(
        """DELETE FROM assistant_messages WHERE user_id = ? AND id < (
               SELECT MIN(id) FROM (
                   SELECT id FROM assistant_messages WHERE user_id = ? ORDER BY id DESC LIMIT 40
               ) t
           )""",
        (user_id, user_id),
    )


@app.route("/assistant")
@login_required
def assistant_page():
    db = get_db()
    history = _load_assistant_history(db, session["user_id"])
    return render_template(
        "assistant.html", history=history, profile=current_profile(),
    )


@app.route("/assistant/message", methods=["POST"])
@login_required
def assistant_message():
    data = request.get_json(silent=True) or {}
    user_message = (data.get("message") or "").strip()
    if not user_message:
        return jsonify({"error": "Message is required."}), 400

    db = get_db()
    history = _load_assistant_history(db, session["user_id"])
    try:
        import assistant
        new_history, reply, cards = assistant.run_agent_turn(
            db, scholarship_matches_profile, session["user_id"], history, user_message,
        )
    except ImportError:
        return jsonify({"error": "Assistant unavailable (install 'openai' package from requirements.txt)."}), 503
    except RuntimeError as e:
        msg = str(e)
        if "फोटो/इमेज" in msg or "image" in msg.lower():
            return jsonify({"error": msg}), 400
        return jsonify({"error": msg}), 503
    except Exception as e:
        msg = str(e)
        if ("this model does not support image input" in msg.lower()
                or "cannot read" in msg.lower()
                or "image input" in msg.lower()
                or "does not support vision" in msg.lower()):
            return jsonify({"error": "अभी तक फोटो/इमेज भेजने की सुविधा उपलब्ध नहीं है। कृपया अपना सवाल टेक्स्ट में टाइप करें।"}), 400
        app.logger.exception("Assistant error")
        return jsonify({"error": "The assistant hit an error. Please try again."}), 502

    _save_assistant_turn(db, session["user_id"], user_message, reply)
    db.commit()
    return jsonify({"reply": reply, "cards": cards})


@app.route("/assistant/reset", methods=["POST"])
@login_required
def assistant_reset():
    db = get_db()
    db.execute("DELETE FROM assistant_messages WHERE user_id = ?", (session["user_id"],))
    db.commit()
    session.pop("assistant_history", None)
    return redirect(url_for("assistant_page"))


init_db()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
