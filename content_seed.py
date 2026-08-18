"""Idempotent enrichment: exam calendar, institutes, roadmap steps, verified flags.

Called on every startup after schema migrate. Safe to re-run.
"""
from matching import CLUSTER_STREAM_LABELS, parse_list
from verified_careers import NEW_VERIFIED, EXTRA_EXAMS, EXTRA_SCHOLARSHIPS

CORE_CAREER_SLUGS = [
    "software-engineer", "data-scientist", "chartered-accountant", "doctor-mbbs",
    "ux-designer", "civil-engineer", "lawyer", "teacher", "mechanical-engineer",
    "psychologist", "digital-marketer", "data-analyst", "architect",
    "civil-services", "pharmacist",
] + [c["slug"] for c in NEW_VERIFIED]

EXAM_CALENDAR = [
    dict(exam_name="JEE Main", exam_code="JEE_MAIN", typical_window="Jan & Apr",
         typical_month=1, next_cycle="2026–27", education_level="Class 11-12",
         streams="pcm,pcmb", clusters="tech,engineering",
         official_url="https://jeemain.nta.nic.in",
         notes="Gateway to NITs, IIITs and many state engineering seats. Two sessions."),
    dict(exam_name="JEE Advanced", exam_code="JEE_ADV", typical_window="May–Jun",
         typical_month=5, next_cycle="2026–27", education_level="Class 11-12",
         streams="pcm,pcmb", clusters="tech,engineering",
         official_url="https://jeeadv.ac.in",
         notes="Only JEE Main qualifiers. For IITs."),
    dict(exam_name="NEET-UG", exam_code="NEET", typical_window="May",
         typical_month=5, next_cycle="2026–27", education_level="Class 11-12",
         streams="pcb,pcmb", clusters="healthcare",
         official_url="https://neet.nta.nic.in",
         notes="MBBS, BDS, AYUSH and many allied health seats."),
    dict(exam_name="CUET-UG", exam_code="CUET", typical_window="May–Jun",
         typical_month=5, next_cycle="2026–27", education_level="Class 11-12",
         streams="pcm,pcb,pcmb,commerce,arts", clusters="tech,science,business,social,creative,law",
         official_url="https://cuet.nta.nic.in",
         notes="Central and many state/private universities."),
    dict(exam_name="CLAT", exam_code="CLAT", typical_window="Dec",
         typical_month=12, next_cycle="2026–27", education_level="Class 11-12",
         streams="arts,commerce,pcm,pcb,pcmb", clusters="law",
         official_url="https://consortiumofnlus.ac.in",
         notes="5-year integrated LLB at National Law Universities."),
    dict(exam_name="AILET", exam_code="AILET", typical_window="Dec",
         typical_month=12, next_cycle="2026–27", education_level="Class 11-12",
         streams="arts,commerce,pcm,pcb,pcmb", clusters="law",
         official_url="https://nationallawuniversitydelhi.in",
         notes="NLU Delhi only."),
    dict(exam_name="NATA", exam_code="NATA", typical_window="Apr–Jul (multiple)",
         typical_month=4, next_cycle="2026–27", education_level="Class 11-12",
         streams="pcm,pcmb,arts", clusters="creative,engineering",
         official_url="https://www.nata.in",
         notes="B.Arch aptitude test. Often paired with JEE Main Paper 2."),
    dict(exam_name="NID DAT", exam_code="NID", typical_window="Jan",
         typical_month=1, next_cycle="2026–27", education_level="Class 11-12",
         streams="arts,pcm,pcb,commerce,pcmb", clusters="creative",
         official_url="https://admissions.nid.edu",
         notes="National Institute of Design. Portfolio matters."),
    dict(exam_name="NIFT", exam_code="NIFT", typical_window="Feb",
         typical_month=2, next_cycle="2026–27", education_level="Class 11-12",
         streams="arts,commerce,pcm,pcb,pcmb", clusters="creative",
         official_url="https://www.nift.ac.in",
         notes="Fashion and design campuses."),
    dict(exam_name="UCEED", exam_code="UCEED", typical_window="Jan",
         typical_month=1, next_cycle="2026–27", education_level="Class 11-12",
         streams="pcm,pcmb,arts", clusters="creative,tech",
         official_url="https://www.uceed.iitb.ac.in",
         notes="B.Des at participating IITs."),
    dict(exam_name="NDA", exam_code="NDA", typical_window="Apr & Sep",
         typical_month=4, next_cycle="2026–27", education_level="Class 11-12",
         streams="pcm,pcmb", clusters="law,engineering",
         official_url="https://upsc.gov.in",
         notes="12th-pass national defence academy exam (UPSC). PCM for Air Force/Navy."),
    dict(exam_name="CUET-PG / GATE", exam_code="GATE", typical_window="Feb (GATE)",
         typical_month=2, next_cycle="2026–27", education_level="Undergraduate",
         streams="pcm,pcmb", clusters="tech,engineering,science",
         official_url="https://gate.iitk.ac.in",
         notes="GATE for M.Tech and many PSU jobs. CUET-PG for master's."),
    dict(exam_name="UPSC CSE", exam_code="UPSC_CSE", typical_window="Prelims May–Jun",
         typical_month=5, next_cycle="2026–27", education_level="Undergraduate",
         streams="pcm,pcb,pcmb,commerce,arts", clusters="law,social",
         official_url="https://upsc.gov.in",
         notes="IAS/IPS/IFS and other central services. Graduation required. Multi-year prep is normal."),
    dict(exam_name="SSC CGL", exam_code="SSC_CGL", typical_window="Varies (often mid-year)",
         typical_month=6, next_cycle="2026–27", education_level="Undergraduate",
         streams="pcm,pcb,pcmb,commerce,arts", clusters="law,business",
         official_url="https://ssc.gov.in",
         notes="Graduate-level central government posts. Recurs most years."),
    dict(exam_name="State PSC / PCS", exam_code="STATE_PSC", typical_window="Varies by state",
         typical_month=8, next_cycle="2026–27", education_level="Undergraduate",
         streams="pcm,pcb,pcmb,commerce,arts", clusters="law",
         official_url="",
         notes="State civil services. Watch your State PSC site. Historical ads stay useful."),
    dict(exam_name="CA Foundation", exam_code="CA_FOUND", typical_window="May & Nov",
         typical_month=5, next_cycle="2026–27", education_level="Class 11-12",
         streams="commerce,pcm,pcmb,arts", clusters="business",
         official_url="https://www.icai.org",
         notes="Can start after Class 12. Then Intermediate, articleship, Final."),
    dict(exam_name="CTET", exam_code="CTET", typical_window="Jul & Dec (typical)",
         typical_month=7, next_cycle="2026–27", education_level="Undergraduate",
         streams="arts,commerce,pcm,pcb,pcmb", clusters="social",
         official_url="https://ctet.nic.in",
         notes="Central Teacher Eligibility Test. State TETs are separate."),
    dict(exam_name="GPAT", exam_code="GPAT", typical_window="May–Jun",
         typical_month=6, next_cycle="2026–27", education_level="Undergraduate",
         streams="pcb,pcmb", clusters="healthcare",
         official_url="https://www.nba.aicte-india.org",
         notes="M.Pharm and some PSU pharmacy roles."),
] + EXTRA_EXAMS

# slug -> enrichment used only for the 15 verified careers
CAREER_ENRICHMENT = {
    "software-engineer": dict(
        riasec="IR",
        wlb="Good", remote="Hybrid", mid=(900000, 2500000), senior=(1800000, 4500000),
        related=["data-scientist", "data-analyst", "machine-learning-engineer"],
        institutes=[
            ("IIT Bombay / Delhi / Madras (CSE)", "IIT", "JEE Advanced", "Govt tuition ~₹2–2.5L/yr"),
            ("NIT / IIIT (CSE/IT)", "NIT/IIIT", "JEE Main", "Govt tuition ~₹1.5–2L/yr"),
            ("IIITs and good state colleges", "State/Private", "JEE Main / state CET", "Varies widely"),
        ],
        steps=[
            ("After Class 10", "Take Science PCM. Add Computer Science if the school offers it.", 1),
            ("After Class 12", "JEE Main / state CET / CUET. B.Tech CSE, IT, or BCA as an alternate.", 2),
            ("During Graduation", "Data structures, one internship, GitHub projects.", 3),
            ("First Job", "SDE intern then junior engineer. System design comes later.", 4),
        ],
    ),
    "data-scientist": dict(
        riasec="I",
        wlb="Good", remote="Mostly Remote", mid=(1200000, 2800000), senior=(2000000, 5000000),
        related=["data-analyst", "software-engineer", "machine-learning-engineer"],
        institutes=[
            ("IITs / ISI / CMI (stats, CS, maths)", "IIT", "JEE / institute tests", "Competitive"),
            ("M.Sc Data Science / M.Stat programmes", "University", "CUET-PG / institute", "1–3 years"),
        ],
        steps=[
            ("After Class 10", "PCM or PCB with strong maths.", 1),
            ("After Class 12", "B.Sc Stats/Math/CS or B.Tech. Learn Python + statistics early.", 2),
            ("During Graduation", "Kaggle-style projects, SQL, one research/analytics internship.", 3),
        ],
    ),
    "chartered-accountant": dict(
        riasec="CE",
        wlb="Demanding", remote="Mostly On-site", mid=(900000, 2000000), senior=(1500000, 4000000),
        related=["digital-marketer", "company-secretary-with-qualification", "cost-accountant"],
        institutes=[
            ("ICAI CA course (any city)", "Professional", "CA Foundation", "Exam + 2-year articleship"),
        ],
        steps=[
            ("After Class 10", "Commerce is the usual path; PCM students also switch.", 1),
            ("After Class 12", "Register for CA Foundation. Articleship after Intermediate.", 2),
            ("Skill Development", "Accounting software, GST, Excel, audit basics.", 3),
        ],
    ),
    "doctor-mbbs": dict(
        riasec="IS",
        wlb="Highly Demanding", remote="Completely On-site", mid=(800000, 1800000), senior=(1500000, 5000000),
        related=["pharmacist", "psychologist"],
        institutes=[
            ("AIIMS and central institutes", "Medical", "NEET-UG", "Bond/service rules vary"),
            ("State government medical colleges", "Medical", "NEET-UG", "State quota + All India quota"),
        ],
        steps=[
            ("After Class 10", "Science PCB is required.", 1),
            ("After Class 12", "NEET-UG. MBBS is 5.5 years including internship.", 2),
            ("Career Growth Milestones", "NEET-PG for MD/MS if you specialise.", 3),
        ],
    ),
    "ux-designer": dict(
        riasec="AI",
        wlb="Good", remote="Hybrid", mid=(700000, 1800000), senior=(1500000, 3500000),
        related=["architect", "digital-marketer"],
        institutes=[
            ("NID / IIT B.Des", "Design", "NID DAT / UCEED", "Portfolio is decisive"),
            ("NIFT or private UX programmes", "Design", "NIFT / institute", "Build a public portfolio"),
        ],
        steps=[
            ("After Class 10", "Any stream works; start sketching and noticing apps you use.", 1),
            ("After Class 12", "B.Des or any degree + UX certificate. NID/UCEED if design school.", 2),
            ("Internships", "2–3 case studies beat a generic certificate pile.", 3),
        ],
    ),
    "civil-engineer": dict(
        riasec="RI",
        wlb="Average", remote="Mostly On-site", mid=(600000, 1400000), senior=(1200000, 2500000),
        related=["mechanical-engineer", "architect"],
        institutes=[
            ("IIT / NIT Civil", "IIT/NIT", "JEE", "Core + site internships matter"),
            ("State engineering colleges / diploma lateral entry", "State", "CET / diploma", "Site experience is the differentiator"),
        ],
        steps=[
            ("After Class 10", "Science PCM, or diploma after 10th.", 1),
            ("After Class 12", "JEE Main / state CET. AutoCAD in the first year.", 2),
            ("Internships", "Site or PMC internship before final year.", 3),
        ],
    ),
    "lawyer": dict(
        riasec="ES",
        wlb="Demanding", remote="Mostly On-site", mid=(500000, 2000000), senior=(1200000, 4000000),
        related=["civil-services", "civil-judge"],
        institutes=[
            ("National Law Universities", "NLU", "CLAT / AILET", "5-year BA LLB"),
            ("3-year LLB after any graduation", "University", "University test", "Good if you decide later"),
        ],
        steps=[
            ("After Class 10", "Arts or Commerce help; any stream can sit CLAT.", 1),
            ("After Class 12", "CLAT / AILET / LSAT India, or graduate first then 3-year LLB.", 2),
            ("During Graduation", "Moot courts, internships with a lawyer or firm.", 3),
        ],
    ),
    "teacher": dict(
        riasec="S",
        wlb="Good", remote="Mostly On-site", mid=(400000, 900000), senior=(700000, 1500000),
        related=["psychologist", "special-educator"],
        institutes=[
            ("B.Ed at a recognised college", "Education", "University / CUET", "CTET / State TET after or during B.Ed"),
            ("B.El.Ed (elementary)", "Education", "University", "For primary teaching"),
        ],
        steps=[
            ("After Class 10", "Any stream. Pick subjects you may want to teach.", 1),
            ("After Class 12", "Bachelor's in a subject, then B.Ed. Or B.El.Ed.", 2),
            ("First Job", "CTET/TET, then school applications. Portfolio of lesson samples helps.", 3),
        ],
    ),
    "mechanical-engineer": dict(
        riasec="RI",
        wlb="Average", remote="Mostly On-site", mid=(600000, 1500000), senior=(1200000, 2800000),
        related=["civil-engineer", "software-engineer"],
        institutes=[
            ("IIT / NIT Mechanical", "IIT/NIT", "JEE", "Core + software skills both useful"),
            ("State engineering / diploma", "State", "CET / diploma", "Shop-floor internships matter"),
        ],
        steps=[
            ("After Class 10", "Science PCM or diploma.", 1),
            ("After Class 12", "JEE / CET. Learn CAD in year one.", 2),
            ("Internships", "Manufacturing, EV, or HVAC internship.", 3),
        ],
    ),
    "psychologist": dict(
        riasec="SI",
        wlb="Good", remote="Hybrid", mid=(500000, 1200000), senior=(900000, 2000000),
        related=["teacher", "doctor-mbbs"],
        institutes=[
            ("BA/B.Sc Psychology (central/state univ.)", "University", "CUET", "PG + RCI for clinical title"),
            ("MA/M.Sc + M.Phil/RCI pathway", "University", "CUET-PG / institute", "Required for clinical psychologist"),
        ],
        steps=[
            ("After Class 10", "Any stream; PCB or Arts both work.", 1),
            ("After Class 12", "Psychology honours via CUET or state universities.", 2),
            ("Skill Development", "Master's, then RCI-recognised training for clinical practice.", 3),
        ],
    ),
    "digital-marketer": dict(
        riasec="EA",
        wlb="Good", remote="Mostly Remote", mid=(600000, 1400000), senior=(1200000, 2500000),
        related=["ux-designer", "data-analyst"],
        institutes=[
            ("Any bachelor's + Google/Meta certifications", "Certificate", "None mandatory", "Portfolio of campaigns"),
            ("BBA / B.Com / BJMC", "University", "CUET / institute", "Intern at a startup or agency"),
        ],
        steps=[
            ("After Class 10", "Any stream.", 1),
            ("After Class 12", "Any degree. Start a small page or blog and measure it.", 2),
            ("Skill Development", "SEO, ads manager, analytics. Two real campaigns.", 3),
        ],
    ),
    "data-analyst": dict(
        riasec="IC",
        wlb="Good", remote="Hybrid", mid=(700000, 1600000), senior=(1400000, 2800000),
        related=["data-scientist", "software-engineer"],
        institutes=[
            ("B.Sc / B.Com / B.Tech + analytics certificate", "Mixed", "CUET / none", "SQL + a BI tool is the floor"),
        ],
        steps=[
            ("After Class 10", "Keep maths. Any stream can switch later.", 1),
            ("After Class 12", "A quantitative bachelor's helps. Learn Excel + SQL this year.", 2),
            ("Internships", "One dashboard internship or campus analytics project.", 3),
        ],
    ),
    "architect": dict(
        riasec="AR",
        wlb="Demanding", remote="Hybrid", mid=(600000, 1600000), senior=(1200000, 3000000),
        related=["civil-engineer", "ux-designer"],
        institutes=[
            ("SPA Delhi / CEPT / JJ / good B.Arch colleges", "Architecture", "NATA / JEE Paper 2", "5-year B.Arch"),
        ],
        steps=[
            ("After Class 10", "PCM is typical; drawing practice starts now.", 1),
            ("After Class 12", "NATA and/or JEE Main Paper 2.", 2),
            ("During Graduation", "Studio portfolio and a firm internship.", 3),
        ],
    ),
    "civil-services": dict(
        riasec="ES",
        wlb="Demanding", remote="Completely On-site", mid=(800000, 1500000), senior=(1500000, 2500000),
        related=["lawyer", "state-pcs-officer"],
        institutes=[
            ("Any recognised bachelor's degree", "University", "UPSC CSE after graduation", "Optional subject should match what you can study for years"),
        ],
        steps=[
            ("After Class 10", "Any stream. Read widely; current affairs later.", 1),
            ("After Class 12", "Pick a bachelor's you enjoy. UPSC is after graduation.", 2),
            ("During Graduation", "NCERTs, newspaper habit, and a realistic 2–3 year plan. Not 'apply this week'.", 3),
        ],
    ),
    "pharmacist": dict(
        riasec="IC",
        wlb="Good", remote="Completely On-site", mid=(350000, 700000), senior=(600000, 1200000),
        related=["doctor-mbbs", "registered-nurse"],
        institutes=[
            ("B.Pharm at PCI-approved college", "Pharmacy", "State / institute exam", "4 years"),
            ("D.Pharm (2 years)", "Pharmacy", "State exam", "Faster entry to a chemist role"),
        ],
        steps=[
            ("After Class 10", "PCB or PCM depending on the college.", 1),
            ("After Class 12", "State pharmacy entrance or D.Pharm.", 2),
            ("First Job", "Hospital / retail / industry. GPAT if you want M.Pharm.", 3),
        ],
    ),
}


def _upsert_lookup(db, table, id_col, name_col, name, extra=None):
    row = db.execute(f"SELECT {id_col} FROM {table} WHERE {name_col} = ?", (name,)).fetchone()
    if row:
        return row[id_col]
    cols = [name_col] + list((extra or {}).keys())
    vals = [name] + list((extra or {}).values())
    placeholders = ",".join(["?"] * len(cols))
    return db.execute(
        f"INSERT INTO {table} ({','.join(cols)}) VALUES ({placeholders}) RETURNING {id_col}",
        vals,
    ).fetchone()[id_col]


def apply_editorial_career(db, spec):
    """Insert or refresh a verified career's core row + demand/salary/skills/exams."""
    from seed_data import _DEMAND_MAP, _FUTURE_DEMAND_MAP

    category_id = _upsert_lookup(db, "career_categories", "category_id", "name", spec["cluster"])
    existing = db.execute("SELECT career_id FROM careers WHERE slug = ?", (spec["slug"],)).fetchone()
    if existing:
        career_id = existing["career_id"]
        db.execute(
            """UPDATE careers SET career_name=?, career_category_id=?, description=?,
               min_education_qualification=?, is_verified=TRUE, updated_at=now()
               WHERE career_id=?""",
            (spec["name"], category_id, spec["description"], spec["education_path"], career_id),
        )
    else:
        code = "CAR-" + spec["slug"].upper().replace("_", "-")
        career_id = db.execute(
            """INSERT INTO careers (career_code, slug, career_name, career_category_id,
               description, min_education_qualification, source, is_verified)
               VALUES (?,?,?,?,?,?,'editorial',TRUE) RETURNING career_id""",
            (code, spec["slug"], spec["name"], category_id,
             spec["description"], spec["education_path"]),
        ).fetchone()["career_id"]

    demand = _DEMAND_MAP.get(spec["demand"], spec["demand"] if spec["demand"] in
                             ("Very High", "High", "Medium", "Low") else "Medium")
    future = _FUTURE_DEMAND_MAP.get(demand, "High")
    db.execute(
        """INSERT INTO career_demand (career_id, current_demand, future_demand) VALUES (?,?,?)
           ON CONFLICT (career_id) DO UPDATE SET current_demand=EXCLUDED.current_demand,
             future_demand=EXCLUDED.future_demand""",
        (career_id, demand, future),
    )
    db.execute(
        """INSERT INTO career_salary_india (career_id, level, min_salary_inr, max_salary_inr)
           VALUES (?, 'Entry Level (0-3 Yrs)', ?, ?)
           ON CONFLICT (career_id, level) DO UPDATE SET min_salary_inr=EXCLUDED.min_salary_inr,
             max_salary_inr=EXCLUDED.max_salary_inr""",
        (career_id, spec.get("salary_min"), spec.get("salary_max")),
    )
    db.execute(
        """INSERT INTO career_automation_risk (career_id, risk_level, future_proof_recommendation)
           VALUES (?, 'Moderate', ?)
           ON CONFLICT (career_id) DO UPDATE SET future_proof_recommendation=EXCLUDED.future_proof_recommendation""",
        (career_id, spec.get("ai_impact")),
    )

    db.execute("DELETE FROM career_skills WHERE career_id = ?", (career_id,))
    for name in parse_list(spec.get("skills", "")):
        sid = _upsert_lookup(db, "skills", "skill_id", "name", name, extra={"skill_type": "Technical"})
        db.execute(
            "INSERT INTO career_skills (career_id, skill_id) VALUES (?,?) ON CONFLICT DO NOTHING",
            (career_id, sid),
        )
    db.execute("DELETE FROM career_entrance_exams WHERE career_id = ?", (career_id,))
    for name in parse_list(spec.get("exams", "")):
        eid = _upsert_lookup(db, "entrance_exams", "exam_id", "name", name, extra={"exam_type": "National"})
        db.execute(
            "INSERT INTO career_entrance_exams (career_id, exam_id) VALUES (?,?) ON CONFLICT DO NOTHING",
            (career_id, eid),
        )
    return career_id


def seed_extra_scholarships(db):
    for s in EXTRA_SCHOLARSHIPS:
        if db.execute("SELECT 1 FROM scholarships WHERE name = ?", (s["name"],)).fetchone():
            continue
        db.execute(
            """INSERT INTO scholarships (name, provider, type, description, education_level,
               states, categories, gender, income_ceiling, amount, deadline, apply_url, documents,
               requires_disability, requires_minority, source)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'editorial')""",
            (s["name"], s["provider"], s["type"], s["description"], s["education_level"],
             s["states"], s["categories"], s["gender"], s["income_ceiling"], s["amount"],
             s["deadline"], s["apply_url"], s["documents"],
             bool(s.get("requires_disability")),
             bool(s.get("requires_minority") or "Minority" in (s.get("categories") or "")),
            ),
        )


def _upsert_riasec_types(db):
    for code, name in (("R", "Realistic"), ("I", "Investigative"), ("A", "Artistic"),
                       ("S", "Social"), ("E", "Enterprising"), ("C", "Conventional")):
        db.execute(
            "INSERT INTO riasec_types (code, name) VALUES (?,?) ON CONFLICT (code) DO NOTHING",
            (code, name),
        )


def _enrichment_map():
    merged = dict(CAREER_ENRICHMENT)
    for spec in NEW_VERIFIED:
        merged[spec["slug"]] = spec
    return merged


CONTENT_VERSION = 3


def _content_version(db):
    try:
        row = db.execute("SELECT value FROM app_meta WHERE key = 'content_version'").fetchone()
        return int(row["value"]) if row and row["value"] else 0
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass
        return 0


def _set_content_version(db, version):
    db.execute(
        """CREATE TABLE IF NOT EXISTS app_meta (key TEXT PRIMARY KEY, value TEXT)"""
    )
    db.execute(
        """INSERT INTO app_meta (key, value) VALUES ('content_version', ?)
           ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value""",
        (str(version),),
    )


def seed_app_content(db):
    """Fill lookup/enrichment tables. Safe on every boot.

    Heavy editorial writes run only when CONTENT_VERSION increases so app
    startup stays fast after the first apply.
    """
    if _content_version(db) >= CONTENT_VERSION:
        return

    for spec in NEW_VERIFIED:
        apply_editorial_career(db, spec)

    slugs = tuple(CORE_CAREER_SLUGS)
    db.execute(
        "UPDATE careers SET is_verified = TRUE WHERE slug IN ({})".format(
            ",".join("?" * len(slugs))
        ),
        slugs,
    )
    db.execute(
        "UPDATE careers SET is_verified = FALSE WHERE slug NOT IN ({})".format(
            ",".join("?" * len(slugs))
        ),
        slugs,
    )

    seed_extra_scholarships(db)
    db.execute(
        "UPDATE scholarships SET requires_disability = TRUE WHERE name ILIKE ?",
        ("%Saksham%",),
    )
    db.execute(
        "UPDATE scholarships SET requires_minority = TRUE WHERE categories ILIKE ?",
        ("%Minority%",),
    )

    existing_exams = {r["exam_name"] for r in db.execute("SELECT exam_name FROM exam_calendar").fetchall()}
    for row in EXAM_CALENDAR:
        if row["exam_name"] in existing_exams:
            continue
        db.execute(
            """INSERT INTO exam_calendar
               (exam_name, exam_code, typical_window, typical_month, next_cycle,
                education_level, streams, clusters, official_url, notes)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (row["exam_name"], row["exam_code"], row["typical_window"], row["typical_month"],
             row["next_cycle"], row["education_level"], row["streams"], row["clusters"],
             row["official_url"], row["notes"]),
        )

    _upsert_riasec_types(db)
    riasec_ids = {r["code"]: r["riasec_id"] for r in db.execute("SELECT riasec_id, code FROM riasec_types").fetchall()}

    slug_rows = db.execute(
        "SELECT career_id, slug FROM careers WHERE slug IN ({})".format(",".join("?" * len(slugs))),
        slugs,
    ).fetchall()
    by_slug = {r["slug"]: r["career_id"] for r in slug_rows}

    cluster_by_slug = {
        "software-engineer": "tech", "data-scientist": "tech", "data-analyst": "tech",
        "chartered-accountant": "business", "digital-marketer": "business",
        "doctor-mbbs": "healthcare", "pharmacist": "healthcare", "psychologist": "healthcare",
        "ux-designer": "creative", "architect": "creative",
        "civil-engineer": "engineering", "mechanical-engineer": "engineering",
        "lawyer": "law", "civil-services": "law", "teacher": "social",
    }
    cluster_by_slug.update({spec["slug"]: spec["cluster"] for spec in NEW_VERIFIED})

    for slug, extra in _enrichment_map().items():
        career_id = by_slug.get(slug)
        if not career_id:
            # Newly inserted editorial rows may not be in the first lookup.
            row = db.execute("SELECT career_id FROM careers WHERE slug = ?", (slug,)).fetchone()
            if not row:
                continue
            career_id = row["career_id"]
            by_slug[slug] = career_id

        stream_label = CLUSTER_STREAM_LABELS.get(cluster_by_slug.get(slug, ""), "")
        if stream_label:
            sid = _get_or_create_stream(db, stream_label.split(" or ")[0].split(",")[0].strip())
            db.execute(
                "INSERT INTO career_streams (career_id, stream_id) VALUES (?,?) ON CONFLICT DO NOTHING",
                (career_id, sid),
            )

        mid = extra.get("mid")
        if mid:
            db.execute(
                """INSERT INTO career_salary_india (career_id, level, min_salary_inr, max_salary_inr)
                   VALUES (?, 'Mid-Level (4-8 Yrs)', ?, ?)
                   ON CONFLICT (career_id, level) DO UPDATE SET
                     min_salary_inr=EXCLUDED.min_salary_inr, max_salary_inr=EXCLUDED.max_salary_inr""",
                (career_id, mid[0], mid[1]),
            )
        senior = extra.get("senior")
        if senior:
            db.execute(
                """INSERT INTO career_salary_india (career_id, level, min_salary_inr, max_salary_inr)
                   VALUES (?, 'Senior Level (9-15 Yrs)', ?, ?)
                   ON CONFLICT (career_id, level) DO UPDATE SET
                     min_salary_inr=EXCLUDED.min_salary_inr, max_salary_inr=EXCLUDED.max_salary_inr""",
                (career_id, senior[0], senior[1]),
            )

        if extra.get("wlb"):
            db.execute(
                """INSERT INTO career_work_life_balance (career_id, rating)
                   VALUES (?,?::wlb_rating)
                   ON CONFLICT (career_id) DO UPDATE SET rating=EXCLUDED.rating""",
                (career_id, extra["wlb"]),
            )
        if extra.get("remote"):
            db.execute(
                """INSERT INTO career_remote_work (career_id, potential)
                   VALUES (?,?::remote_potential)
                   ON CONFLICT (career_id) DO UPDATE SET potential=EXCLUDED.potential""",
                (career_id, extra["remote"]),
            )

        db.execute("DELETE FROM career_riasec WHERE career_id = ?", (career_id,))
        for letter in extra.get("riasec") or "":
            rid = riasec_ids.get(letter)
            if rid:
                db.execute(
                    "INSERT INTO career_riasec (career_id, riasec_id) VALUES (?,?) ON CONFLICT DO NOTHING",
                    (career_id, rid),
                )

        if extra.get("institutes"):
            db.execute("DELETE FROM career_institutes WHERE career_id = ?", (career_id,))
            for name, kind, entrance, fees in extra["institutes"]:
                db.execute(
                    """INSERT INTO career_institutes (career_id, name, kind, entrance, typical_fees)
                       VALUES (?,?,?,?,?)""",
                    (career_id, name, kind, entrance, fees),
                )

        if extra.get("steps"):
            db.execute("DELETE FROM career_roadmap_steps WHERE career_id = ?", (career_id,))
            for stage, desc, order in extra["steps"]:
                db.execute(
                    """INSERT INTO career_roadmap_steps (career_id, stage, description, sequence_order)
                       VALUES (?,?::roadmap_stage,?,?)""",
                    (career_id, stage, desc, order),
                )

        for rel_slug in extra.get("related") or []:
            other = by_slug.get(rel_slug)
            if other:
                db.execute(
                    "INSERT INTO related_careers (career_id, related_career_id) VALUES (?,?) ON CONFLICT DO NOTHING",
                    (career_id, other),
                )
                db.execute(
                    "INSERT INTO related_careers (career_id, related_career_id) VALUES (?,?) ON CONFLICT DO NOTHING",
                    (other, career_id),
                )

    _set_content_version(db, CONTENT_VERSION)


def _get_or_create_stream(db, name):
    row = db.execute("SELECT stream_id FROM streams WHERE name = ?", (name,)).fetchone()
    if row:
        return row["stream_id"]
    return db.execute(
        "INSERT INTO streams (name) VALUES (?) RETURNING stream_id", (name,)
    ).fetchone()["stream_id"]
