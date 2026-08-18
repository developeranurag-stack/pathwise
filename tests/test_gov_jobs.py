from gov_jobs import (
    backfill_issuer_fields,
    build_search_document,
    display_title,
    exam_kind_label,
    is_incomplete_title,
    posts_heading,
)


def test_display_title_prefers_exam_name():
    assert display_title({
        "exam_name": "State Service Examination 2025",
        "job_title": "1. State Civil Service (Deputy Collector)",
        "commission": "CGPSC",
    }) == "State Service Examination 2025"


def test_display_title_avoids_numbered_cadre():
    assert is_incomplete_title("1. Indian Administrative Service")
    assert display_title({
        "job_title": "1. Indian Administrative Service",
        "commission": "UPSC",
    }) == "UPSC notification"


def test_exam_kind_labels_and_headings():
    assert exam_kind_label("combined_exam") == "Combined exam"
    assert posts_heading("combined_exam") == "Cadres in this exam"
    assert posts_heading("multi_post_ad") == "Posts in this advertisement"
    assert posts_heading("single_post") == "Posts in this notification"


def test_search_document_includes_aliases_and_posts():
    blob = build_search_document(
        {
            "job_title": "CGPSC State Service Examination 2025",
            "commission": "CGPSC",
            "exam_name": "State Service Examination 2025",
            "search_aliases": ["cgpsc", "sse", "psc.cg.gov.in"],
        },
        [{"post_name": "Deputy Collector"}, {"post_name": "DSP"}],
    )
    assert "cgpsc" in blob
    assert "deputy collector" in blob
    assert "state service examination 2025" in blob


def test_backfill_issuer_from_title():
    out = backfill_issuer_fields({
        "job_title": "CGPSC State Service Examination 2025",
        "department": "Chhattisgarh Public Service Commission",
    })
    assert out.get("commission") == "CGPSC"
    assert out.get("state") == "Chhattisgarh"


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows


class _FakeDB:
    def __init__(self, rows=None, fail_if=None):
        self.rows = rows or []
        self.fail_if = fail_if
        self.sqls = []
        self.rolled_back = False

    def execute(self, sql, params=()):
        self.sqls.append((sql, params))
        if self.fail_if and self.fail_if in sql:
            raise RuntimeError("undefined column")
        return _FakeResult(self.rows)

    def rollback(self):
        self.rolled_back = True


def test_fetch_gov_jobs_uses_search_document_and_posts():
    from gov_jobs import fetch_gov_jobs

    db = _FakeDB(rows=[{"id": 1, "job_title": "x", "post_count": 3}])
    rows = fetch_gov_jobs(db, q="cgl")
    assert rows and rows[0]["id"] == 1
    sql, params = db.sqls[0]
    assert "search_document" in sql
    assert "gov_job_posts" in sql
    assert any("cgl" in str(p).lower() or "ssc" in str(p).lower() for p in params)


def test_fetch_gov_jobs_falls_back_without_mcp_columns():
    from gov_jobs import fetch_gov_jobs

    db = _FakeDB(rows=[{"id": 2, "job_title": "y"}], fail_if="search_document")
    rows = fetch_gov_jobs(db, q="upsc")
    assert rows[0]["id"] == 2
    assert db.rolled_back
    assert "search_document" not in db.sqls[-1][0]
