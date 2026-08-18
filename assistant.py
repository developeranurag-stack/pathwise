"""Agentic career/scholarship + government jobs assistant: a function-calling loop over PathWise's
own data, run against a model on OpenRouter.
The agent can read careers/scholarships/gov-jobs and (for gov jobs only) write new notifications
when the user provides advertisement text or material.
"""
import json
import os
import re

from psycopg.types.json import Jsonb

from gov_job_aliases import (
    expand_gov_job_query,
    fallback_terms,
    haystack_matches,
    row_search_haystack,
    sql_terms,
)

# openai imported lazily inside _client() so the rest of the app (and clear_db.py etc)
# can start without the optional openai package.

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
OPENROUTER_MODEL = os.environ.get("OPENROUTER_MODEL", "openai/gpt-4o-mini")

MAX_TOOL_ITERATIONS = 5
MAX_HISTORY_MESSAGES = 12

SYSTEM_PROMPT = """You are PathWise India's career, scholarship and government jobs assistant (PathWise ka career, scholarship aur sarkari naukri sahayak). You help Indian students figure out which careers suit them, which scholarships they're eligible for, and find relevant government job notifications — using ONLY the app's own data via your tools. Never invent career names, salary figures, education paths, scholarship details, job vacancy numbers, deadlines, pay, or eligibility.

Reply in the language the student is using in their messages. Default to Hindi in Devanagari script \
(हिंदी में, देवनागरी लिपि में) unless the student writes in English or explicitly asks to "talk in \
English", "speak English", etc. When the user requests English, switch to clear English for the rest \
of the conversation. Keep proper nouns — career names, scholarship names, exam names, commission \
names, place names, job titles — in their original English/Roman form (even inside Hindi sentences), \
since that's how students search for them in the app.

Before recommending anything, make sure you know the student's education level, interests, state, \
category, gender, and income bracket. Call get_student_profile first to see what's already saved; \
only ask the student directly for whatever is still missing, one or two questions at a time — \
don't interrogate them all at once. Once you have enough to search, call the appropriate tools and \
summarize the real results by name so the student can look them up in the app. If a tool returns nothing, say so plainly in the current language rather than guessing.

EDUCATION-LEVEL AWARENESS (critical for Indian students):
- Class 9-10: do NOT just list careers that require graduation. Suggest the RIGHT STREAM after Class 10 (Science/PCM, Science/PCB, Commerce, Arts/Humanities) based on their interests, and mention exams they can start preparing for now or after Class 11 (JEE Main, NEET, CUET, CLAT). NDA is the rare 12th-pass national exam; CSE / State Service (SSE/PCS) / SSC CGL are graduation-later goals — frame them as long-term paths, not "apply this week".
- Class 11-12: focus on entrance-exam prep (JEE/NEET/CUET/CLAT, and NDA/CDS/Navy if relevant). Treat SSE/CSE/CGL as undergrad-then-exam pathways. Do not tell a 12th-pass student to apply this week unless the tool result's apply window AND qualification clearly say 12th pass.
- Undergraduate / graduate: discuss eligibility, optional subjects, prelims/mains stages, and state domicile when the notification's state matches the student's profile. Internships, certifications, and postgraduate options still apply.

GOVERNMENT EXAMS AND JOBS:
Students ask by acronym or exam brand — "cgpsc", "upsc cse", "mppsc", "ssc cgl", "pcs", "ras", "nda" — even when the stored row uses a full commission name, Hindi, a PDF filename, or only a cadre post like "Deputy Collector". ALWAYS call search_gov_jobs with what they typed. The tool expands aliases (UPSC, all State PSCs, SSC, RRB, High Courts, banking exams, Hindi names, URL hosts). If it still returns no rows, say the database has no matching notification — do NOT invent a UPSC/SSC/PSC vacancy that is not in the tool result.

Combined exams (UPSC CSE, State Service / SSE / PCS / CCE, SSC CGL, ESE, NDA, CDS): talk about the *exam* first — commission, year if present, stages, apply window — then list cadres/posts from the tool. Do not describe a combined exam as "1 vacancy for Deputy Collector" just because a messy title looks like that. If posts[] or exam_name exist, prefer those. If job_title looks like "1. …", say the stored details may be incomplete and still show the row.

Multi-post ads (UPSC Special Ad, High Court, medical college): summarise each post the tool returned. Quote pay and vacancy counts only when those fields are present in the tool result.

Prefer notifications whose state matches the student's state, but NEVER hide national exams (UPSC / SSC / RRB) and NEVER say a student cannot sit UPSC because they are from a particular state.

Historical notifications stay in the answer — vacancies recur in later years. Label passed apply_end_date values clearly as closed/historical.

You can save a career, scholarship or gov job to the student's roadmap, and update missing profile fields, when they ask you to. Use update_student_profile only for facts they stated (stream, state, education, interests, etc.). Use save_item after they confirm they want it saved.

ingest_gov_job is ONLY for when the user pastes advertisement text or describes a screenshot of an official ad. Do not ingest on a bare question like "cgpsc batao"."""

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_student_profile",
            "description": "Get the student's saved onboarding profile (education level, state, "
                            "category, gender, income bracket, interests), if any.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_careers",
            "description": "Search PathWise's career database by interest cluster and/or a free-text "
                            "query against career name/description.",
            "parameters": {
                "type": "object",
                "properties": {
                    "clusters": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Interest cluster keys to filter by, e.g. 'tech', 'science', "
                                       "'business'. Leave empty to search all clusters.",
                    },
                    "query": {
                        "type": "string",
                        "description": "Free-text search against career name/description. Leave "
                                       "empty to skip.",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_career_details",
            "description": "Get full details for a single career by its slug.",
            "parameters": {
                "type": "object",
                "properties": {"slug": {"type": "string"}},
                "required": ["slug"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_scholarships",
            "description": "Find scholarships matching a given eligibility profile (education "
                            "level, state, category, gender, income bracket). Any field can be "
                            "omitted.",
            "parameters": {
                "type": "object",
                "properties": {
                    "education_level": {"type": "string"},
                    "state": {"type": "string"},
                    "category": {"type": "string"},
                    "gender": {"type": "string"},
                    "income_bracket": {"type": "integer"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_gov_jobs",
            "description": "Search stored government job / exam notifications. "
                           "Always call this when the student names a commission or exam brand "
                           "(cgpsc, upsc, cse, mppsc, ssc cgl, ras, pcs, nda, rrb ntpc, high court, …) "
                           "even if you only know the acronym — the tool expands aliases to full "
                           "commission names, Hindi, state names, URL hosts and filename stems, and "
                           "matches title, department, posts, PDF path and optional commission/"
                           "exam_name/search_document columns. Pass the student's words; do not try "
                           "to guess the full commission name yourself. "
                           "Returns historical records too — vacancies recur in later years. "
                           "If the list is empty, the database has no matching notification; say so "
                           "and do not invent vacancies. Combined exams: use exam_name / posts[] "
                           "when present; a title like '1. …' may be an incomplete extraction.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Student's words: acronym, exam brand, state, Hindi name, "
                                       "or free text. The tool expands aliases.",
                    },
                    "department": {"type": "string", "description": "Optional extra filter by department name."},
                    "limit": {"type": "integer", "description": "Max results, default 10."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_gov_job_details",
            "description": "Get complete details for one gov job / exam notification by its numeric id, "
                           "including individual posts, vacancies, dates and pay levels. "
                           "Use after search_gov_jobs when the student wants depth on one row. "
                           "A title that starts with '1.' may be an incomplete extraction of a "
                           "combined exam — prefer posts[] and any exam_name/commission fields; "
                           "do not invent missing commission or vacancy figures.",
            "parameters": {
                "type": "object",
                "properties": {"job_id": {"type": "integer"}},
                "required": ["job_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_student_profile",
            "description": "Update fields on the student's saved profile. Only pass fields they just told you.",
            "parameters": {
                "type": "object",
                "properties": {
                    "education_level": {"type": "string"},
                    "state": {"type": "string"},
                    "category": {"type": "string"},
                    "gender": {"type": "string"},
                    "income_bracket": {"type": "integer"},
                    "stream": {"type": "string", "description": "pcm, pcb, pcmb, commerce, arts, vocational, undecided"},
                    "interests": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Interest cluster keys: tech, science, business, creative, healthcare, social, engineering, law",
                    },
                    "has_disability": {"type": "boolean"},
                    "is_minority": {"type": "boolean"},
                    "is_rural": {"type": "boolean"},
                    "is_first_generation": {"type": "boolean"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "save_item",
            "description": "Save a career (by slug), scholarship (by id), or gov job (by id) to the student's roadmap.",
            "parameters": {
                "type": "object",
                "properties": {
                    "item_type": {"type": "string", "enum": ["career", "scholarship", "gov_job"]},
                    "slug": {"type": "string", "description": "Career slug"},
                    "item_id": {"type": "integer", "description": "Scholarship or gov-job id"},
                },
                "required": ["item_type"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_exams",
            "description": "Search the exam calendar (JEE, NEET, CUET, CLAT, UPSC, SSC, NDA, ...).",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "education_level": {"type": "string"},
                    "stream": {"type": "string"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ingest_gov_job",
            "description": "Save a new gov job notification (and its posts) from advertisement text "
                           "or a screenshot description the user pasted. Do NOT call this for a bare "
                           "question like 'cgpsc batao' — search_gov_jobs first. "
                           "Pass a JSON string. Always ingest even if the deadline is past — "
                           "vacancies recur in following years.",
            "parameters": {
                "type": "object",
                "properties": {
                    "data": {
                        "type": "string",
                        "description": "JSON string like {\"notification\": {\"job_title\": \"...\", \"department\": \"...\", \"total_vacancies\": 5, \"apply_end_date\": \"...\"}, \"posts\": [{\"post_name\": \"...\", \"total_vacancies\": 5}]}"
                    }
                },
                "required": ["data"],
            },
        },
    },
]


def _client():
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise RuntimeError(
            "OPENROUTER_API_KEY is not set. Add it to your .env file to enable the assistant."
        )
    from openai import OpenAI
    return OpenAI(api_key=api_key, base_url=OPENROUTER_BASE_URL)


def _career_row_to_dict(row):
    return {
        "career_id": row["career_id"],
        "slug": row["slug"],
        "name": row["name"],
        "cluster": row["cluster"],
        "demand": row["demand"],
        "salary_min": row["salary_min"],
        "salary_max": row["salary_max"],
        "ai_impact": row["ai_impact"],
        "is_verified": bool(row.get("is_verified")),
        "exams": row.get("exams"),
    }


def tool_get_student_profile(db, user_id):
    if not user_id:
        return {"profile": None}
    row = db.execute("SELECT * FROM profiles WHERE user_id = ?", (user_id,)).fetchone()
    if not row:
        return {"profile": None}
    interests = []
    if row.get("interests"):
        try:
            interests = json.loads(row["interests"])
        except (TypeError, ValueError):
            interests = []
    riasec = []
    if row.get("riasec_codes"):
        try:
            riasec = json.loads(row["riasec_codes"])
        except (TypeError, ValueError):
            riasec = []
    return {
        "profile": {
            "education_level": row["education_level"],
            "state": row["state"],
            "category": row["category"],
            "gender": row["gender"],
            "income_bracket": row["income_bracket"],
            "interests": interests,
            "stream": row.get("stream"),
            "board": row.get("board"),
            "marks_band": row.get("marks_band"),
            "has_disability": bool(row.get("has_disability")),
            "is_minority": bool(row.get("is_minority")),
            "is_rural": bool(row.get("is_rural")),
            "is_first_generation": bool(row.get("is_first_generation")),
            "riasec_codes": riasec,
        }
    }


def tool_search_careers(db, clusters=None, query=None):
    clauses = []
    params = []

    if clusters:
        placeholders = ",".join("?" for _ in clusters)
        clauses.append(f"cluster IN ({placeholders})")
        params.extend(clusters)

    if query:
        clauses.append("(name ILIKE ? OR description ILIKE ? OR COALESCE(exams,'') ILIKE ?)")
        like = f"%{query}%"
        params.extend([like, like, like])

    sql = "SELECT * FROM career_app_view"
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY is_verified DESC, name LIMIT 10"

    rows = db.execute(sql, params).fetchall()
    return {"careers": [_career_row_to_dict(r) for r in rows]}


def tool_get_career_details(db, slug):
    row = db.execute("SELECT * FROM career_app_view WHERE slug = ?", (slug,)).fetchone()
    if not row:
        return {"career": None}
    return {"career": dict(row)}


def tool_search_scholarships(db, scholarship_matcher, education_level=None, state=None,
                              category=None, gender=None, income_bracket=None):
    profile = {
        "education_level": education_level,
        "state": state,
        "category": category,
        "gender": gender,
        "income_bracket": income_bracket,
    }
    rows = db.execute("SELECT * FROM scholarships ORDER BY deadline").fetchall()
    matches = [r for r in rows if scholarship_matcher(r, profile)][:10]
    return {
        "scholarships": [
            {
                "id": r["id"],
                "name": r["name"],
                "provider": r["provider"],
                "amount": r["amount"],
                "deadline": str(r["deadline"]) if r["deadline"] else None,
            }
            for r in matches
        ]
    }


# Optional columns pathwise-mcp may add later. Search uses them when present
# and keeps working on today's schema if they are not.
_OPTIONAL_GOV_JOB_COLS = ("commission", "state", "exam_name", "exam_kind", "search_document")
_gov_job_col_cache = None  # frozenset of column names, or None if unknown


def _is_undefined_column(exc):
    try:
        from psycopg.errors import UndefinedColumn
        if isinstance(exc, UndefinedColumn):
            return True
    except ImportError:
        pass
    msg = str(exc).lower()
    return "undefinedcolumn" in msg or (
        "column" in msg and "does not exist" in msg
    )


def _gov_job_notification_columns(db):
    global _gov_job_col_cache
    if _gov_job_col_cache is not None:
        return _gov_job_col_cache
    rows = db.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = 'public' AND table_name = 'gov_job_notifications'"
    ).fetchall()
    _gov_job_col_cache = frozenset(r["column_name"] for r in rows)
    return _gov_job_col_cache


def _mark_optional_gov_job_cols_missing():
    global _gov_job_col_cache
    if _gov_job_col_cache is None:
        _gov_job_col_cache = frozenset()
    else:
        _gov_job_col_cache = frozenset(
            c for c in _gov_job_col_cache if c not in _OPTIONAL_GOV_JOB_COLS
        )


def _normalize_search_limit(limit):
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        return 10
    if limit <= 0:
        return 10
    return min(limit, 50)


def _like_pattern(term):
    escaped = (
        str(term)
        .replace("\\", "\\\\")
        .replace("%", "\\%")
        .replace("_", "\\_")
    )
    return f"%{escaped}%"


def _gov_job_select_cols(cols):
    select = [
        "n.id",
        "n.job_title",
        "n.department",
        "n.advertisement_number",
        "n.official_url",
        "n.local_pdf_path",
        "n.qualification",
        "n.total_vacancies",
        "n.apply_start_date",
        "n.apply_end_date",
        "n.exam_date",
    ]
    extra = [c for c in _OPTIONAL_GOV_JOB_COLS if c in cols]
    select.extend(f"n.{c}" for c in extra)
    return select, extra


def _gov_job_search_blob_sql(extra_cols):
    """Computed search document from existing columns + posts + basename.

    Prefer n.search_document when MCP has added it; still OR the computed blob
    so imperfect historical rows remain findable.
    """
    parts = [
        "n.job_title",
        "n.department",
        "n.advertisement_number",
        "COALESCE(n.official_url, '')",
        "COALESCE(n.local_pdf_path, '')",
        "REPLACE(REPLACE(LOWER(COALESCE(n.local_pdf_path, '')), '_', ' '), '-', ' ')",
        "COALESCE(n.qualification, '')",
        "COALESCE(n.translations::text, '')",
        "("
        "SELECT string_agg(CONCAT_WS(' ', p.post_name, p.department), ' ') "
        "FROM gov_job_posts p WHERE p.notification_id = n.id"
        ")",
    ]
    for c in extra_cols:
        if c == "search_document":
            continue
        parts.append(f"COALESCE(n.{c}::text, '')")
    blob = "LOWER(CONCAT_WS(' ', " + ", ".join(parts) + "))"
    if "search_document" in extra_cols:
        return f"(LOWER(COALESCE(n.search_document, '')) || ' ' || {blob})"
    return blob


def _shape_gov_job_row(row, post_names):
    """Return model-facing fields; omit nulls and columns that do not exist."""
    keys = (
        "id",
        "job_title",
        "department",
        "commission",
        "state",
        "exam_name",
        "exam_kind",
        "advertisement_number",
        "official_url",
        "total_vacancies",
        "apply_start_date",
        "apply_end_date",
        "exam_date",
    )
    out = {}
    for k in keys:
        if k not in row.keys():
            continue
        val = row[k]
        if val is None or val == "":
            continue
        out[k] = val
    names = [n for n in post_names if n]
    if names:
        extra = len(names) - 8
        if extra > 0:
            out["posts"] = names[:8] + [f"and {extra} more"]
        else:
            out["posts"] = names
    return out


def _posts_by_notification(db, notification_ids):
    if not notification_ids:
        return {}
    placeholders = ",".join("?" for _ in notification_ids)
    rows = db.execute(
        f"SELECT notification_id, post_name FROM gov_job_posts "
        f"WHERE notification_id IN ({placeholders}) ORDER BY id",
        tuple(notification_ids),
    ).fetchall()
    grouped = {}
    for r in rows:
        grouped.setdefault(r["notification_id"], []).append(r["post_name"])
    return grouped


def _shape_gov_job_rows(db, rows):
    posts = _posts_by_notification(db, [r["id"] for r in rows])
    return [_shape_gov_job_row(r, posts.get(r["id"], [])) for r in rows]


def _list_recent_gov_jobs(db, limit):
    cols = _gov_job_notification_columns(db)
    select, _extra = _gov_job_select_cols(cols)
    sql = (
        "SELECT " + ", ".join(select)
        + " FROM gov_job_notifications n ORDER BY n.created_at DESC LIMIT ?"
    )
    rows = db.execute(sql, (limit,)).fetchall()
    return {"jobs": _shape_gov_job_rows(db, rows)}


def _sql_search_gov_jobs(db, terms, department, limit):
    """One round-trip: OR every term against the computed search document."""
    cols = _gov_job_notification_columns(db)
    select, extra = _gov_job_select_cols(cols)
    blob = _gov_job_search_blob_sql(extra)
    clauses = []
    params = []
    terms = [t for t in (terms or []) if t and str(t).strip()]
    if terms:
        term_clause = " OR ".join(f"{blob} LIKE ?" for _ in terms)
        clauses.append("(" + term_clause + ")")
        params.extend(_like_pattern(str(t).lower()) for t in terms)
    if department:
        clauses.append("n.department ILIKE ?")
        params.append(f"%{department}%")
    sql = "SELECT " + ", ".join(select) + " FROM gov_job_notifications n"
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY n.created_at DESC LIMIT ?"
    params.append(limit)
    try:
        return db.execute(sql, tuple(params)).fetchall()
    except Exception as e:
        if not _is_undefined_column(e):
            raise
        try:
            db.rollback()
        except Exception:
            pass
        _mark_optional_gov_job_cols_missing()
        cols = _gov_job_notification_columns(db)
        select, extra = _gov_job_select_cols(cols)
        blob = _gov_job_search_blob_sql(extra)
        clauses = []
        params = []
        if terms:
            term_clause = " OR ".join(f"{blob} LIKE ?" for _ in terms)
            clauses.append("(" + term_clause + ")")
            params.extend(_like_pattern(str(t).lower()) for t in terms)
        if department:
            clauses.append("n.department ILIKE ?")
            params.append(f"%{department}%")
        sql = "SELECT " + ", ".join(select) + " FROM gov_job_notifications n"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY n.created_at DESC LIMIT ?"
        params.append(limit)
        return db.execute(sql, tuple(params)).fetchall()


def _python_alias_search(db, expansion, department, limit):
    """Scan recent rows when SQL misses (underscores, Hindi, imperfect titles)."""
    cols = _gov_job_notification_columns(db)
    select, _extra = _gov_job_select_cols(cols)
    sql = (
        "SELECT " + ", ".join(select) + ", n.translations "
        "FROM gov_job_notifications n ORDER BY n.created_at DESC LIMIT ?"
    )
    try:
        candidates = db.execute(sql, (200,)).fetchall()
    except Exception as e:
        if not _is_undefined_column(e):
            raise
        try:
            db.rollback()
        except Exception:
            pass
        _mark_optional_gov_job_cols_missing()
        cols = _gov_job_notification_columns(db)
        select, _extra = _gov_job_select_cols(cols)
        sql = (
            "SELECT " + ", ".join(select) + ", n.translations "
            "FROM gov_job_notifications n ORDER BY n.created_at DESC LIMIT ?"
        )
        candidates = db.execute(sql, (200,)).fetchall()

    dept_needle = (department or "").strip().lower()
    ids = [r["id"] for r in candidates]
    posts = {}
    if ids:
        placeholders = ",".join("?" for _ in ids)
        for p in db.execute(
            f"SELECT notification_id, post_name, department FROM gov_job_posts "
            f"WHERE notification_id IN ({placeholders})",
            tuple(ids),
        ).fetchall():
            posts.setdefault(p["notification_id"], []).append(p)

    hits = []
    for row in candidates:
        if dept_needle:
            dept = (row.get("department") or "").lower()
            if dept_needle not in dept:
                continue
        hay = row_search_haystack(row, posts.get(row["id"]))
        if haystack_matches(hay, expansion):
            hits.append(row)
        if len(hits) >= limit:
            break
    return hits


def tool_search_gov_jobs(db, query=None, department=None, limit=10):
    """Search stored government job notifications.

    Expands exam/commission acronyms, matches existing columns plus optional
    MCP columns when present, and retries with aliases / state / exam phrase
    so "cgpsc" hits a row that only says Chhattisgarh + STATE_SERVICE_EXAMINATION.
    Historical rows are kept (no apply_end_date filter) because vacancies recur.
    """
    limit = _normalize_search_limit(limit)
    raw = (query or "").strip()
    if not raw and not department:
        return _list_recent_gov_jobs(db, limit)

    expansion = expand_gov_job_query(raw)
    if expansion.get("soft_only") and not department:
        return _list_recent_gov_jobs(db, limit)

    # First pass: original + expanded aliases in one OR query.
    # When an issuer is known, shared phrases like "state service" are left
    # out so "mppsc" does not match every other state's SSE PDF.
    rows = _sql_search_gov_jobs(db, sql_terms(expansion), department, limit)

    # If still empty, retry with just the state name or just the exam phrase.
    if not rows:
        narrow = fallback_terms(expansion)
        if narrow:
            rows = _sql_search_gov_jobs(db, narrow, department, limit)

    # Last resort: Python-side alias check against recent rows (path/Hindi/state).
    if not rows and raw:
        rows = _python_alias_search(db, expansion, department, limit)

    return {"jobs": _shape_gov_job_rows(db, rows)}


def tool_get_gov_job_details(db, job_id):
    """Get full details for one gov job notification including its individual posts."""
    job = db.execute("SELECT * FROM gov_job_notifications WHERE id = ?", (job_id,)).fetchone()
    if not job:
        return {"job": None}
    posts = db.execute("SELECT * FROM gov_job_posts WHERE notification_id = ? ORDER BY id", (job_id,)).fetchall()
    return {
        "job": dict(job),
        "posts": [dict(p) for p in posts]
    }


def tool_ingest_gov_job(db, data):
    """Ingest a government job notification (and its posts) from user-provided material such as pasted text from a PDF advertisement.
    The 'data' must be a JSON string with 'notification' object (at minimum job_title) and optional 'posts' array.
    Always save the record even if the deadline has passed — similar vacancies recur in following years.
    Set source to 'assistant-ingest' if not provided.
    """
    try:
        payload = json.loads(data)
        notif = payload.get("notification") or {}
        posts = payload.get("posts") or []

        if not notif.get("job_title"):
            return {"error": "notification.job_title is required"}

        # Prepare notification insert
        nparams = [
            notif.get("job_title"),
            notif.get("department"),
            notif.get("total_vacancies"),
            Jsonb(notif.get("reservation_details")) if notif.get("reservation_details") else None,
            notif.get("nationality"),
            notif.get("qualification"),
            notif.get("age_limit"),
            notif.get("age_relaxation"),
            Jsonb(notif.get("age_relaxation_details")) if notif.get("age_relaxation_details") else None,
            notif.get("apply_start_date"),
            notif.get("apply_end_date"),
            notif.get("exam_date"),
            notif.get("advertisement_number"),
            notif.get("application_fee"),
            notif.get("official_url"),
            notif.get("local_pdf_path"),
            notif.get("source", "assistant-ingest"),
            Jsonb(notif.get("translations")) if notif.get("translations") else None,
            Jsonb(notif.get("syllabus")) if notif.get("syllabus") else None,
        ]

        row = db.execute("""
            INSERT INTO gov_job_notifications (
                job_title, department, total_vacancies, reservation_details, nationality,
                qualification, age_limit, age_relaxation, age_relaxation_details,
                apply_start_date, apply_end_date, exam_date, advertisement_number,
                application_fee, official_url, local_pdf_path, source, translations, syllabus
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            RETURNING id
        """, nparams).fetchone()
        notif_id = row["id"]

        for p in posts:
            pparams = [
                notif_id,
                p.get("post_name"),
                p.get("department"),
                p.get("pay_level"),
                p.get("total_vacancies"),
                Jsonb(p.get("vacancies_breakdown")) if p.get("vacancies_breakdown") else None,
                p.get("qualification"),
                Jsonb(p.get("translations")) if p.get("translations") else None,
            ]
            db.execute("""
                INSERT INTO gov_job_posts (
                    notification_id, post_name, department, pay_level, total_vacancies,
                    vacancies_breakdown, qualification, translations
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, pparams)

        return {
            "success": True,
            "notification_id": notif_id,
            "message": f"Saved gov job notification #{notif_id} (including historical records for recurring vacancies)."
        }
    except Exception as e:
        return {"error": f"Ingest failed: {str(e)}"}


def tool_update_student_profile(db, user_id, **fields):
    if not user_id:
        return {"error": "Not logged in"}
    row = db.execute("SELECT * FROM profiles WHERE user_id = ?", (user_id,)).fetchone()
    allowed = {
        "education_level", "state", "category", "gender", "income_bracket", "stream",
        "has_disability", "is_minority", "is_rural", "is_first_generation",
    }
    updates = {k: v for k, v in fields.items() if k in allowed and v is not None}
    interests = fields.get("interests")
    if not row:
        db.execute(
            """INSERT INTO profiles (user_id, education_level, state, category, gender,
               income_bracket, interests, stream, has_disability, is_minority, is_rural,
               is_first_generation)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (user_id, updates.get("education_level"), updates.get("state"),
             updates.get("category"), updates.get("gender"), updates.get("income_bracket"),
             json.dumps(interests or []), updates.get("stream"),
             bool(updates.get("has_disability")), bool(updates.get("is_minority")),
             bool(updates.get("is_rural")), bool(updates.get("is_first_generation"))),
        )
        return {"success": True, "created": True, "updated": list(updates.keys()) + (["interests"] if interests else [])}

    sets, params = [], []
    for k, v in updates.items():
        sets.append(f"{k} = ?")
        params.append(v)
    if interests is not None:
        sets.append("interests = ?")
        params.append(json.dumps(interests))
    if not sets:
        return {"success": True, "updated": []}
    params.append(user_id)
    db.execute(f"UPDATE profiles SET {', '.join(sets)} WHERE user_id = ?", params)
    return {"success": True, "updated": list(updates.keys()) + (["interests"] if interests is not None else [])}


def tool_save_item(db, user_id, item_type, slug=None, item_id=None):
    if not user_id:
        return {"error": "Not logged in"}
    now = __import__("datetime").datetime.utcnow().isoformat()
    if item_type == "career":
        if not slug:
            return {"error": "slug required for career"}
        career = db.execute("SELECT career_id, name FROM career_app_view WHERE slug = ?", (slug,)).fetchone()
        if not career:
            return {"error": "Career not found"}
        db.execute(
            "INSERT INTO saved_careers (user_id, career_id, created_at) VALUES (?,?,?) ON CONFLICT DO NOTHING",
            (user_id, career["career_id"], now),
        )
        return {"success": True, "saved": career["name"], "type": "career"}
    if item_type == "scholarship":
        if not item_id:
            return {"error": "item_id required for scholarship"}
        sch = db.execute("SELECT id, name FROM scholarships WHERE id = ?", (item_id,)).fetchone()
        if not sch:
            return {"error": "Scholarship not found"}
        db.execute(
            "INSERT INTO saved_scholarships (user_id, scholarship_id, created_at) VALUES (?,?,?) ON CONFLICT DO NOTHING",
            (user_id, sch["id"], now),
        )
        return {"success": True, "saved": sch["name"], "type": "scholarship"}
    if item_type == "gov_job":
        if not item_id:
            return {"error": "item_id required for gov_job"}
        job = db.execute("SELECT id, job_title FROM gov_job_notifications WHERE id = ?", (item_id,)).fetchone()
        if not job:
            return {"error": "Job not found"}
        db.execute(
            "INSERT INTO saved_gov_jobs (user_id, notification_id) VALUES (?,?) ON CONFLICT DO NOTHING",
            (user_id, job["id"]),
        )
        return {"success": True, "saved": job["job_title"], "type": "gov_job"}
    return {"error": f"Unknown item_type: {item_type}"}


def tool_search_exams(db, query=None, education_level=None, stream=None):
    rows = db.execute("SELECT * FROM exam_calendar ORDER BY typical_month NULLS LAST, exam_name").fetchall()
    q = (query or "").lower().strip()
    out = []
    for r in rows:
        blob = " ".join([
            r.get("exam_name") or "", r.get("exam_code") or "", r.get("notes") or "",
            r.get("clusters") or "", r.get("streams") or "",
        ]).lower()
        if q and q not in blob:
            continue
        if education_level and r.get("education_level") and education_level not in r["education_level"]:
            continue
        if stream and r.get("streams") and stream not in (r["streams"] or "") and "all" not in (r["streams"] or ""):
            continue
        out.append({
            "exam_name": r["exam_name"],
            "typical_window": r["typical_window"],
            "next_cycle": r["next_cycle"],
            "education_level": r["education_level"],
            "official_url": r["official_url"],
            "notes": r["notes"],
        })
        if len(out) >= 10:
            break
    return {"exams": out}


def _strip_markdown(text):
    if not text:
        return text
    text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
    text = re.sub(r'\*(.+?)\*', r'\1', text)
    text = re.sub(r'`(.+?)`', r'\1', text)
    text = re.sub(r'\[(.+?)\]\(.+?\)', r'\1', text)
    text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)
    text = re.sub(r'^\s*[-*]\s+', '', text, flags=re.MULTILINE)
    return text


def _is_image_input_error(e):
    msg = str(e).lower()
    return ("this model does not support image input" in msg
            or "cannot read" in msg
            or "image input" in msg
            or "does not support vision" in msg)


def run_agent_turn(db, scholarship_matcher, user_id, history, user_message):
    """Runs one turn of the agentic loop: appends user_message to history, lets the
    model call tools against PathWise's data as needed, and returns the updated
    history, the model's final text reply, and any career/scholarship result cards
    gathered along the way.
    """
    client = _client()

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend(history)
    messages.append({"role": "user", "content": user_message})

    cards = []

    try:
        for _ in range(MAX_TOOL_ITERATIONS):
            response = client.chat.completions.create(
                model=OPENROUTER_MODEL,
                messages=messages,
                tools=TOOLS,
            )
            choice = response.choices[0]
            msg = choice.message

            if not msg.tool_calls:
                messages.append({"role": "assistant", "content": msg.content or ""})
                new_history = messages[1:][-MAX_HISTORY_MESSAGES:]
                return new_history, _strip_markdown(msg.content or ""), cards

            messages.append({
                "role": "assistant",
                "content": msg.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                    }
                    for tc in msg.tool_calls
                ],
            })

            for tc in msg.tool_calls:
                args = json.loads(tc.function.arguments or "{}")
                result = _dispatch_tool(db, scholarship_matcher, user_id, tc.function.name, args)

                if tc.function.name == "search_careers" and result.get("careers"):
                    cards.extend({"type": "career", **c} for c in result["careers"])
                elif tc.function.name == "search_scholarships" and result.get("scholarships"):
                    cards.extend({"type": "scholarship", **s} for s in result["scholarships"])
                elif tc.function.name == "search_gov_jobs" and result.get("jobs"):
                    for j in result["jobs"]:
                        cards.append({
                            "type": "gov_job",
                            "id": j.get("id"),
                            "title": j.get("exam_name") or j.get("job_title"),
                            "subtitle": j.get("commission") or j.get("department"),
                            "apply_end_date": j.get("apply_end_date"),
                        })

                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": json.dumps(result, default=str),
                })

        new_history = messages[1:][-MAX_HISTORY_MESSAGES:]
        fallback = "I wasn't able to finish that lookup — could you rephrase or narrow your question?"
        return new_history, _strip_markdown(fallback), cards
    except Exception as e:
        if _is_image_input_error(e):
            raise RuntimeError(
                "अभी तक फोटो/इमेज भेजने की सुविधा उपलब्ध नहीं है। कृपया अपना सवाल टेक्स्ट में टाइप करें।"
            )
        raise


def _dispatch_tool(db, scholarship_matcher, user_id, name, args):
    if name == "get_student_profile":
        return tool_get_student_profile(db, user_id)
    if name == "search_careers":
        return tool_search_careers(db, clusters=args.get("clusters"), query=args.get("query"))
    if name == "get_career_details":
        return tool_get_career_details(db, args.get("slug"))
    if name == "search_scholarships":
        return tool_search_scholarships(
            db, scholarship_matcher,
            education_level=args.get("education_level"), state=args.get("state"),
            category=args.get("category"), gender=args.get("gender"),
            income_bracket=args.get("income_bracket"),
        )
    if name == "search_gov_jobs":
        return tool_search_gov_jobs(
            db, query=args.get("query"), department=args.get("department"), limit=args.get("limit")
        )
    if name == "get_gov_job_details":
        return tool_get_gov_job_details(db, args.get("job_id"))
    if name == "ingest_gov_job":
        return tool_ingest_gov_job(db, args.get("data"))
    if name == "update_student_profile":
        return tool_update_student_profile(db, user_id, **args)
    if name == "save_item":
        return tool_save_item(
            db, user_id, item_type=args.get("item_type"),
            slug=args.get("slug"), item_id=args.get("item_id"),
        )
    if name == "search_exams":
        return tool_search_exams(
            db, query=args.get("query"),
            education_level=args.get("education_level"), stream=args.get("stream"),
        )
    return {"error": f"Unknown tool: {name}"}
