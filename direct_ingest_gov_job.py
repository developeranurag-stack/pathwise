"""Direct ingestion of government job notifications into the DB.

This allows the AI agent (or manual use) to create job records directly
from uploaded material (PDF text, OCR, screenshots, etc.) without relying
on the external pathwise-mcp.

Usage:
    python direct_ingest_gov_job.py data.json

The JSON should have:
{
  "notification": {
    "job_title": "...",
    "department": "...",
    "total_vacancies": 22,
    "advertisement_number": "51/2026",
    "apply_start_date": "29/09/2025",
    "apply_end_date": "28/10/2025",
    "exam_date": "04/01/2026",
    "qualification": "...",
    "age_limit": "...",
    "application_fee": "...",
    "official_url": "...",
    "local_pdf_path": "optional/path/to/pdf.pdf",
    "source": "ai-direct",   // or "manual"
    "reservation_details": {"UR": 10, "SC": 5, ...},  // optional JSON
    "translations": {"hi": {...}},  // optional
    "syllabus": {...}  // optional
  },
  "posts": [
    {
      "post_name": "Court Manager",
      "total_vacancies": 22,
      "pay_level": "Level-10",
      "vacancies_breakdown": {"UR": 10, ...},
      "qualification": "..."
    }
  ]
}

Even past deadlines are stored because similar vacancies recur in following years.
"""

import sys
import json
from pathlib import Path

import db as dbmod
from psycopg.types.json import Jsonb


def insert_gov_job(notification: dict, posts: list = None):
    """Insert a notification + optional posts directly.

    Returns the new notification id.
    """
    if not notification.get("job_title"):
        raise ValueError("job_title is required")

    conn = dbmod.connect()
    cur = conn.cursor()

    try:
        # Insert notification
        cur.execute("""
            INSERT INTO gov_job_notifications (
                job_title, department, total_vacancies, reservation_details,
                nationality, qualification, age_limit, age_relaxation,
                age_relaxation_details, apply_start_date, apply_end_date,
                exam_date, advertisement_number, application_fee, official_url,
                local_pdf_path, source, translations, syllabus
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            ) RETURNING id
        """, (
            notification.get("job_title"),
            notification.get("department"),
            notification.get("total_vacancies"),
            Jsonb(notification.get("reservation_details")) if notification.get("reservation_details") else None,
            notification.get("nationality"),
            notification.get("qualification"),
            notification.get("age_limit"),
            notification.get("age_relaxation"),
            Jsonb(notification.get("age_relaxation_details")) if notification.get("age_relaxation_details") else None,
            notification.get("apply_start_date"),
            notification.get("apply_end_date"),
            notification.get("exam_date"),
            notification.get("advertisement_number"),
            notification.get("application_fee"),
            notification.get("official_url"),
            notification.get("local_pdf_path"),
            notification.get("source", "ai-direct"),
            Jsonb(notification.get("translations")) if notification.get("translations") else None,
            Jsonb(notification.get("syllabus")) if notification.get("syllabus") else None,
        ))
        notif_id = cur.fetchone()["id"]

        # Insert posts if any
        posts = posts or []
        for p in posts:
            cur.execute("""
                INSERT INTO gov_job_posts (
                    notification_id, post_name, department, pay_level,
                    total_vacancies, vacancies_breakdown, qualification, translations
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                notif_id,
                p.get("post_name"),
                p.get("department"),
                p.get("pay_level"),
                p.get("total_vacancies"),
                Jsonb(p.get("vacancies_breakdown")) if p.get("vacancies_breakdown") else None,
                p.get("qualification"),
                Jsonb(p.get("translations")) if p.get("translations") else None,
            ))

        conn.commit()
        return notif_id

    finally:
        conn.close()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python direct_ingest_gov_job.py <data.json>")
        print("See docstring for JSON structure.")
        sys.exit(1)

    json_path = Path(sys.argv[1])
    if not json_path.exists():
        print(f"File not found: {json_path}")
        sys.exit(1)

    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    notif = data.get("notification", {})
    posts_list = data.get("posts", [])

    try:
        nid = insert_gov_job(notif, posts_list)
        print(f"Successfully inserted notification #{nid}")
        print(f"  Title: {notif.get('job_title')}")
        print(f"  Posts: {len(posts_list)}")
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)
