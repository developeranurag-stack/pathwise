"""Shared gov-job read helpers.

pathwise-mcp writes gov_job_notifications / gov_job_posts. PathWise only
SELECTs those rows — this module is the app-facing query and display layer
described in ../pathwise-mcp/INTEGRATING.md.
"""
from __future__ import annotations

import re

from gov_job_aliases import ISSUERS, expand_gov_job_query, sql_terms


EXAM_KINDS = (
    ("combined_exam", "Combined exam"),
    ("multi_post_ad", "Multiple posts"),
    ("single_post", "Single post"),
    ("departmental_exam", "Departmental exam"),
)
EXAM_KIND_LABELS = {k: label for k, label in EXAM_KINDS}

_CADRE_KINDS = frozenset({"combined_exam", "departmental_exam"})
_BAD_TITLE_RE = re.compile(r"^\s*\d+\.\s+")


def _like_pattern(term):
    escaped = (
        str(term)
        .replace("\\", "\\\\")
        .replace("%", "\\%")
        .replace("_", "\\_")
    )
    return f"%{escaped}%"


# INTEGRATING.md search: aliases blob + issuer + exam + title + cadre posts.
_TERM_MATCH_SQL = """(
    LOWER(COALESCE(n.search_document, '')) LIKE ?
    OR LOWER(COALESCE(n.commission, '')) LIKE ?
    OR LOWER(COALESCE(n.exam_name, '')) LIKE ?
    OR LOWER(n.job_title) LIKE ?
    OR LOWER(COALESCE(n.department, '')) LIKE ?
    OR EXISTS (
        SELECT 1 FROM gov_job_posts p
        WHERE p.notification_id = n.id
          AND (LOWER(p.post_name) LIKE ?
               OR LOWER(COALESCE(p.department, '')) LIKE ?)
    )
)"""
_TERM_PARAM_COUNT = 7

_FALLBACK_TERM_SQL = """(
    LOWER(n.job_title) LIKE ?
    OR LOWER(COALESCE(n.department, '')) LIKE ?
    OR LOWER(COALESCE(n.exam_name, '')) LIKE ?
    OR LOWER(COALESCE(n.commission, '')) LIKE ?
)"""
_FALLBACK_PARAM_COUNT = 4


def is_incomplete_title(title):
    return bool(title and _BAD_TITLE_RE.match(str(title)))


def display_title(job):
    """Prefer the exam brand; avoid numbered-cadre extracts as the heading."""
    exam = (job.get("exam_name") or "").strip()
    if exam:
        return exam
    title = (job.get("job_title") or "").strip()
    if is_incomplete_title(title):
        commission = (job.get("commission") or "").strip()
        if commission:
            return f"{commission} notification"
    return title


def exam_kind_label(kind):
    kind = (kind or "").strip()
    return EXAM_KIND_LABELS.get(kind, "")


def posts_heading(kind):
    if kind in _CADRE_KINDS:
        return "Cadres in this exam"
    if kind == "multi_post_ad":
        return "Posts in this advertisement"
    return "Posts in this notification"


def build_search_document(notif, posts=None):
    """Lowercase alias blob so assistant-ingested rows stay findable."""
    parts = []
    seen = set()

    def _add(value):
        text = " ".join(str(value or "").lower().split())
        if text and text not in seen:
            seen.add(text)
            parts.append(text)

    for alias in notif.get("search_aliases") or []:
        _add(alias)
    for key in ("commission", "state", "exam_name", "exam_kind", "job_title", "department"):
        _add(notif.get(key))
    for post in posts or []:
        _add(post.get("post_name"))
        _add(post.get("department"))
    existing = notif.get("search_document")
    if existing:
        _add(existing)
    return " ".join(parts)


def backfill_issuer_fields(notif):
    """Fill commission/state from the registry when ingest skipped them."""
    out = dict(notif)
    if out.get("commission") and (out.get("state") or out.get("exam_name")):
        return out
    blob = " ".join(
        str(out.get(k) or "")
        for k in ("job_title", "exam_name", "department", "commission")
    ).strip()
    if not blob:
        return out
    expansion = expand_gov_job_query(blob)
    if not out.get("commission") and expansion.get("issuer"):
        out["commission"] = expansion["issuer"]
    if not out.get("state") and expansion.get("state"):
        out["state"] = expansion["state"]
    if not out.get("exam_name") and expansion.get("exam_hint"):
        out["exam_name"] = expansion["exam_hint"].replace("_", " ")
    return out


def annotate_job(row):
    item = dict(row)
    kind = (item.get("exam_kind") or "").strip()
    post_count = item.get("post_count")
    if post_count is None:
        post_count = 0
    item["display_title"] = display_title(item)
    item["exam_kind_label"] = exam_kind_label(kind)
    item["posts_heading"] = posts_heading(kind)
    item["show_vacancies"] = bool(item.get("total_vacancies"))
    item["extract_incomplete"] = is_incomplete_title(item.get("job_title"))
    if kind in _CADRE_KINDS and post_count:
        item["posts_badge"] = f"{post_count} cadres"
    elif post_count > 1:
        item["posts_badge"] = f"{post_count} posts"
    else:
        item["posts_badge"] = None
    item["post_count"] = post_count
    return item


def _search_where(q, commission, state, exam_kind, term_sql, param_count):
    clauses, params = [], []
    q = (q or "").strip()
    if q:
        expansion = expand_gov_job_query(q)
        if not expansion.get("soft_only"):
            terms = sql_terms(expansion) or [q]
            parts = []
            for term in terms:
                parts.append(term_sql)
                params.extend([_like_pattern(str(term).lower())] * param_count)
            clauses.append("(" + " OR ".join(parts) + ")")
    if commission:
        clauses.append("COALESCE(n.commission,'') ILIKE ?")
        params.append(f"%{commission}%")
    if state:
        clauses.append(
            "(COALESCE(n.state,'') ILIKE ? OR COALESCE(n.department,'') ILIKE ?)"
        )
        params.extend([f"%{state}%", f"%{state}%"])
    if exam_kind:
        clauses.append("COALESCE(n.exam_kind,'') = ?")
        params.append(exam_kind)
    return clauses, params


def fetch_gov_jobs(db, q="", commission="", state="", exam_kind=""):
    """List notifications using MCP search columns + alias expansion."""
    commission = (commission or "").strip()
    state = (state or "").strip()
    exam_kind = (exam_kind or "").strip()
    select = (
        "SELECT n.*, "
        "(SELECT COUNT(*) FROM gov_job_posts p WHERE p.notification_id = n.id) "
        "AS post_count "
        "FROM gov_job_notifications n"
    )
    clauses, params = _search_where(
        q, commission, state, exam_kind, _TERM_MATCH_SQL, _TERM_PARAM_COUNT
    )
    sql = select
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY n.created_at DESC"
    try:
        return db.execute(sql, tuple(params)).fetchall()
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass
        clauses, params = _search_where(
            q, commission, state, exam_kind, _FALLBACK_TERM_SQL, _FALLBACK_PARAM_COUNT
        )
        # Older DBs may lack exam_kind / search_document / posts.
        sql = "SELECT * FROM gov_job_notifications n"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY n.created_at DESC"
        try:
            return db.execute(sql, tuple(params)).fetchall()
        except Exception:
            try:
                db.rollback()
            except Exception:
                pass
            return db.execute(
                "SELECT * FROM gov_job_notifications ORDER BY created_at DESC"
            ).fetchall()


def related_gov_jobs(db, exam_names, limit=4):
    seen = set()
    out = []
    for name in [n for n in (exam_names or []) if n][:3]:
        for row in fetch_gov_jobs(db, q=name):
            if row["id"] in seen:
                continue
            seen.add(row["id"])
            out.append(row)
            if len(out) >= limit:
                return out
    return out


def distinct_commissions(db):
    try:
        rows = db.execute(
            "SELECT DISTINCT commission FROM gov_job_notifications "
            "WHERE commission IS NOT NULL AND commission <> '' ORDER BY commission"
        ).fetchall()
        values = [r["commission"] for r in rows]
        if values:
            return values
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass
    return [iss["code"] for iss in ISSUERS]
