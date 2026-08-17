"""Agentic career/scholarship + government jobs assistant: a function-calling loop over PathWise's
own data, run against a model on OpenRouter.
The agent can read careers/scholarships/gov-jobs and (for gov jobs only) write new notifications
when the user provides advertisement text or material.
"""
import json
import os

from psycopg.types.json import Jsonb

# openai imported lazily inside _client() so the rest of the app (and clear_db.py etc)
# can start without the optional openai package.

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
OPENROUTER_MODEL = os.environ.get("OPENROUTER_MODEL", "openai/gpt-4o-mini")

MAX_TOOL_ITERATIONS = 5
MAX_HISTORY_MESSAGES = 12

SYSTEM_PROMPT = """You are PathWise India's career, scholarship and government jobs assistant (PathWise ka career, scholarship aur sarkari naukri sahayak). You help Indian students figure out which careers suit them, which scholarships they're eligible for, and find relevant government job notifications — using ONLY the app's own data via your tools. Never invent career names, salary figures, education paths, scholarship details, or job vacancy numbers.

Reply in the language the student is using in their messages. Default to Hindi in Devanagari script \
(हिंदी में, देवनागरी लिपि में) unless the student writes in English or explicitly asks to "talk in \
English", "speak English", etc. When the user requests English, switch to clear English for the rest \
of the conversation. Keep proper nouns — career names, scholarship names, exam names, place names, \
job titles — in their original English/Roman form (even inside Hindi sentences), since that's how students search for them in the app.

Before recommending anything, make sure you know the student's education level, interests, state, \
category, gender, and income bracket. Call get_student_profile first to see what's already saved; \
only ask the student directly for whatever is still missing, one or two questions at a time — \
don't interrogate them all at once. Once you have enough to search, call the appropriate tools and \
summarize the real results by name so the student can look them up in the app. If a tool returns nothing, say so plainly in the current language rather than guessing.

EDUCATION-LEVEL AWARENESS (critical for Indian students):
- If the student is in Class 9-10, do NOT just list careers that require graduation/postgraduation. Instead, suggest the RIGHT STREAM after Class 10 (Science/PCM, Science/PCB, Commerce, Arts/Humanities) based on their interests, and mention which exams they can start preparing for NOW or after Class 11 (e.g. JEE Main, NEET, CUET, CLAT). Frame long-term careers as goals to work toward, not immediate exam targets.
- If the student is in Class 11-12, focus on entrance-exam prep (JEE/NEET/CUET/CLAT etc.) and undergraduate pathways.
- If the student is already in undergraduate or higher, discuss internships, certifications, and postgraduate options.

GOVERNMENT JOBS: The database stores official job notifications (including historical ones). Vacancies for similar posts frequently recur in following years even after a deadline has passed — ALWAYS keep and surface historical records when ingesting or searching. When the user pastes or describes text from a job advertisement PDF (or screenshot), call ingest_gov_job with a clean JSON payload built from what they provided. Do not skip or drop records just because the apply_end_date is in the past."""

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
            "description": "Search government job notifications by keyword (title, dept, ad number) or department. "
                           "Returns historical records too — vacancies often recur in later years even after deadlines pass.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Free text search in title/dept/ad-number."},
                    "department": {"type": "string", "description": "Filter by department name."},
                    "limit": {"type": "integer", "description": "Max results, default 10."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_gov_job_details",
            "description": "Get complete details for one gov job notification by its numeric id, including all individual posts, vacancies, dates and pay levels.",
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
            "name": "ingest_gov_job",
            "description": "Save a new gov job notification (and its posts) into the database from text the user provides from an official advertisement PDF or description. "
                           "Pass a JSON string. Always ingest even if deadline is past — vacancies come back in following years. Use when user shares ad material.",
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
    }


def tool_get_student_profile(db, user_id):
    if not user_id:
        return {"profile": None}
    row = db.execute("SELECT * FROM profiles WHERE user_id = ?", (user_id,)).fetchone()
    if not row:
        return {"profile": None}
    return {
        "profile": {
            "education_level": row["education_level"],
            "state": row["state"],
            "category": row["category"],
            "gender": row["gender"],
            "income_bracket": row["income_bracket"],
            "interests": json.loads(row["interests"]) if row["interests"] else [],
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
        clauses.append("(name ILIKE ? OR description ILIKE ?)")
        like = f"%{query}%"
        params.extend([like, like])

    sql = "SELECT * FROM career_app_view"
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY name LIMIT 10"

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


def tool_search_gov_jobs(db, query=None, department=None, limit=10):
    """Search stored government job notifications. Use for finding ads by keyword, department or ad number.
    Always include historical ads (even with passed deadlines) because similar vacancies recur in following years.
    """
    sql = "SELECT id, job_title, department, total_vacancies, apply_end_date, advertisement_number, created_at FROM gov_job_notifications"
    clauses = []
    params = []
    if query:
        clauses.append("(job_title ILIKE ? OR department ILIKE ? OR advertisement_number ILIKE ?)")
        like = f"%{query}%"
        params.extend([like, like, like])
    if department:
        clauses.append("department ILIKE ?")
        params.append(f"%{department}%")
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)
    rows = db.execute(sql, params).fetchall()
    return {"jobs": [dict(r) for r in rows]}


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
    return {"error": f"Unknown tool: {name}"}
