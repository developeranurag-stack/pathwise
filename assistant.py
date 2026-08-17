"""Agentic career/scholarship assistant: a function-calling loop over PathWise's
own data, run against a model on OpenRouter (an OpenAI-compatible API gateway).
Tools are read-only — the agent looks things up via career_app_view /
scholarships and the existing matching helpers in main.py, it never writes to
the database.
"""
import json
import os

from openai import OpenAI

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
OPENROUTER_MODEL = os.environ.get("OPENROUTER_MODEL", "openai/gpt-4o-mini")

MAX_TOOL_ITERATIONS = 5
MAX_HISTORY_MESSAGES = 12

SYSTEM_PROMPT = """You are PathWise India's career and scholarship assistant (PathWise ka career \
aur scholarship sahayak). You help Indian students figure out which careers suit them and which \
scholarships they're eligible for, using only the app's own data via your tools — never invent \
career names, salary figures, education paths, or scholarship details.

Reply in the language the student is using in their messages. Default to Hindi in Devanagari script \
(हिंदी में, देवनागरी लिपि में) unless the student writes in English or explicitly asks to "talk in \
English", "speak English", etc. When the user requests English, switch to clear English for the rest \
of the conversation. Keep proper nouns — career names, scholarship names, exam names, place names — \
in their original English/Roman form (even inside Hindi sentences), since that's how students search \
for them in the app.

Before recommending anything, make sure you know the student's education level, interests, state, \
category, gender, and income bracket. Call get_student_profile first to see what's already saved; \
only ask the student directly for whatever is still missing, one or two questions at a time — \
don't interrogate them all at once. Once you have enough to search, call search_careers and/or \
search_scholarships and summarize the real results by name so the student can look them up in the \
app. If a tool returns nothing, say so plainly in the current language rather than guessing."""

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
]


def _client():
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise RuntimeError(
            "OPENROUTER_API_KEY is not set. Add it to your .env file to enable the assistant."
        )
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
            return new_history, msg.content or "", cards

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
    return new_history, fallback, cards


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
    return {"error": f"Unknown tool: {name}"}
