"""Pluggable ingestion for careers/scholarships from external program listings.

Each "source" (see the `sources` table) is a URL plus a named parser. Running a
source fetches its URL, hands the HTML to the parser, and upserts whatever
rows it returns into `careers` or `scholarships`, tagged with
source='scraper:<source name>' so admins can tell auto-added rows apart from
rows they entered by hand.

To add a new site: write a parser function below that takes the page's HTML
text and returns a list of dicts matching the career/scholarship column
shapes, then register it in PARSERS.
"""
import datetime
import re

import requests
from bs4 import BeautifulSoup

USER_AGENT = "PathWiseBot/1.0 (+admin-configured scholarship/career sync)"


class ScrapeError(Exception):
    pass


def fetch_html(url):
    resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=20)
    resp.raise_for_status()
    return resp.text


def generic_html_table(html):
    """Best-effort parser for a plain HTML table of programs.

    Expects a <table> with a header row containing recognizable column names
    (name/title, description, deadline/last date, provider, amount, apply
    link). Works for simple static government/NGO listing pages; will not
    work for JavaScript-rendered (SPA) sites such as myscheme.gov.in, which
    load data via client-side API calls rather than server-rendered HTML.
    """
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table")
    if not table:
        raise ScrapeError(
            "No <table> found in the page. This parser only supports static "
            "HTML tables; JavaScript-rendered sites need a custom parser."
        )

    rows = table.find_all("tr")
    if len(rows) < 2:
        raise ScrapeError("Table has no data rows.")

    headers = [c.get_text(strip=True).lower() for c in rows[0].find_all(["th", "td"])]

    def col(cells, *names):
        for name in names:
            for i, h in enumerate(headers):
                if name in h and i < len(cells):
                    return cells[i].get_text(strip=True)
        return ""

    results = []
    for tr in rows[1:]:
        cells = tr.find_all("td")
        if not cells:
            continue
        name = col(cells, "name", "title", "scheme")
        if not name:
            continue
        link_el = tr.find("a", href=True)
        results.append({
            "name": name,
            "provider": col(cells, "provider", "department", "ministry"),
            "type": col(cells, "type", "category") or "Government",
            "description": col(cells, "description", "detail", "about"),
            "education_level": col(cells, "education", "level", "eligibility"),
            "states": col(cells, "state") or "All",
            "categories": col(cells, "category") or "All",
            "gender": col(cells, "gender") or "All",
            "income_ceiling": _parse_int(col(cells, "income")),
            "amount": col(cells, "amount", "benefit"),
            "deadline": _parse_date(col(cells, "deadline", "last date", "due")),
            "apply_url": link_el["href"] if link_el else "",
            "documents": col(cells, "document"),
        })
    return results


def _parse_int(value):
    digits = re.sub(r"[^\d]", "", value or "")
    return int(digits) if digits else None


def _parse_date(value):
    if not value:
        return None
    for fmt in ("%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d", "%d %B %Y", "%d %b %Y"):
        try:
            return datetime.datetime.strptime(value.strip(), fmt).date().isoformat()
        except ValueError:
            continue
    return value.strip()


PARSERS = {
    "generic_html_table": generic_html_table,
}


def run_source(db, source):
    """Fetch + parse a source row, upsert results, and return a status string.

    `db` is a db.Connection (sqlite-style `.execute(sql_with_?, params)`
    wrapper around the Postgres connection); `source` is a row from the
    `sources` table. Scholarships are upserted by name; careers by slug
    derived from name. Existing rows that were entered manually are left
    untouched if a scraped row would collide by name/slug (manual entries
    always win) — only rows tagged as coming from this same scraper source
    get overwritten on re-run.
    """
    parser = PARSERS.get(source["parser"])
    if not parser:
        return "error", f"Unknown parser '{source['parser']}'"

    try:
        html = fetch_html(source["url"])
        records = parser(html)
    except requests.RequestException as e:
        return "error", f"Fetch failed: {e}"
    except ScrapeError as e:
        return "error", str(e)

    if not records:
        return "error", "Parser returned no records."

    now = datetime.datetime.utcnow().isoformat()
    tag = f"scraper:{source['name']}"
    added, skipped = 0, 0

    if source["target_type"] == "scholarship":
        for r in records:
            existing = db.execute(
                "SELECT id, source FROM scholarships WHERE name = ?", (r["name"],)
            ).fetchone()
            if existing and existing["source"] != tag:
                skipped += 1
                continue
            if existing:
                db.execute(
                    """UPDATE scholarships SET provider=?, type=?, description=?, education_level=?,
                       states=?, categories=?, gender=?, income_ceiling=?, amount=?, deadline=?,
                       apply_url=?, documents=?, source_url=?, last_synced_at=? WHERE id=?""",
                    (r["provider"], r["type"], r["description"], r["education_level"], r["states"],
                     r["categories"], r["gender"], r["income_ceiling"], r["amount"], r["deadline"],
                     r["apply_url"], r["documents"], source["url"], now, existing["id"]),
                )
            else:
                db.execute(
                    """INSERT INTO scholarships (name, provider, type, description, education_level,
                       states, categories, gender, income_ceiling, amount, deadline, apply_url,
                       documents, source, source_url, last_synced_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (r["name"], r["provider"], r["type"], r["description"], r["education_level"],
                     r["states"], r["categories"], r["gender"], r["income_ceiling"], r["amount"],
                     r["deadline"], r["apply_url"], r["documents"], tag, source["url"], now),
                )
            added += 1
    else:
        for r in records:
            slug = re.sub(r"[^a-z0-9]+", "-", r["name"].lower()).strip("-")
            existing = db.execute(
                "SELECT career_id, source FROM careers WHERE slug = ?", (slug,)
            ).fetchone()
            if existing and existing["source"] != tag:
                skipped += 1
                continue

            category_name = r.get("cluster") or "other"
            category_row = db.execute(
                "SELECT category_id FROM career_categories WHERE name = ?", (category_name,)
            ).fetchone()
            if category_row:
                category_id = category_row["category_id"]
            else:
                category_id = db.execute(
                    "INSERT INTO career_categories (name) VALUES (?) RETURNING category_id", (category_name,)
                ).fetchone()["category_id"]

            if existing:
                career_id = existing["career_id"]
                db.execute(
                    """UPDATE careers SET career_name=?, career_category_id=?, description=?,
                       source_url=?, last_synced_at=? WHERE career_id=?""",
                    (r["name"], category_id, r["description"], source["url"], now, career_id),
                )
            else:
                career_code = "CAR-" + slug.upper()
                career_id = db.execute(
                    """INSERT INTO careers (career_code, slug, career_name, career_category_id,
                       description, source, source_url, last_synced_at)
                       VALUES (?,?,?,?,?,?,?,?) RETURNING career_id""",
                    (career_code, slug, r["name"], category_id, r["description"], tag, source["url"], now),
                ).fetchone()["career_id"]

            demand = r.get("demand") or "Medium"
            if demand not in ("Very High", "High", "Medium", "Low"):
                demand = "Medium"
            future_demand = "Declining" if demand == "Low" else demand
            db.execute(
                """INSERT INTO career_demand (career_id, current_demand, future_demand) VALUES (?,?,?)
                   ON CONFLICT (career_id) DO UPDATE SET current_demand=EXCLUDED.current_demand,
                     future_demand=EXCLUDED.future_demand""",
                (career_id, demand, future_demand),
            )

            if r.get("salary_min") is not None or r.get("salary_max") is not None:
                db.execute(
                    """INSERT INTO career_salary_india (career_id, level, min_salary_inr, max_salary_inr)
                       VALUES (?, 'Entry Level (0-3 Yrs)', ?, ?)
                       ON CONFLICT (career_id, level) DO UPDATE SET min_salary_inr=EXCLUDED.min_salary_inr,
                         max_salary_inr=EXCLUDED.max_salary_inr""",
                    (career_id, r.get("salary_min"), r.get("salary_max")),
                )

            added += 1

    db.commit()
    msg = f"Added/updated {added} record(s)."
    if skipped:
        msg += f" Skipped {skipped} that collided with manually-entered rows."
    return "success", msg
