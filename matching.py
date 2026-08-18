"""Career / scholarship / gov-job matching used by routes and the assistant."""
import datetime
import json
import re

STREAMS = [
    ("pcm", "Science (PCM)"),
    ("pcb", "Science (PCB)"),
    ("pcmb", "Science (PCMB)"),
    ("commerce", "Commerce"),
    ("arts", "Arts / Humanities"),
    ("vocational", "Vocational / Diploma"),
    ("undecided", "Not sure yet"),
]

BOARDS = ["CBSE", "CISCE / ICSE", "State board", "NIOS", "Other"]

MARKS_BANDS = [
    ("below_50", "Below 50%"),
    ("50_60", "50–60%"),
    ("60_75", "60–75%"),
    ("75_90", "75–90%"),
    ("90_plus", "90%+"),
]

SUBJECT_OPTIONS = [
    "Mathematics", "Physics", "Chemistry", "Biology", "Computer Science",
    "Accountancy", "Business Studies", "Economics", "History",
    "Political Science", "Geography", "English", "Fine Arts",
]

STREAM_CLUSTERS = {
    "pcm": {"tech", "engineering", "science"},
    "pcb": {"healthcare", "science"},
    "pcmb": {"tech", "engineering", "science", "healthcare"},
    "commerce": {"business", "law"},
    "arts": {"law", "social", "creative"},
    "vocational": {"engineering", "creative", "tech", "business"},
    "undecided": set(),
}

CLUSTER_STREAM_LABELS = {
    "tech": "Science (PCM)",
    "science": "Science (PCM/PCB)",
    "engineering": "Science (PCM)",
    "healthcare": "Science (PCB)",
    "business": "Commerce",
    "law": "Arts or Commerce",
    "social": "Arts / Humanities",
    "creative": "Arts, or any stream + portfolio",
}

EDU_TOKENS = {
    "Class 9-10": ("class 9", "class 10", "class 9-10", "class 9-12", "9-10", "9-12", "secondary"),
    "Class 11-12": ("class 11", "class 12", "class 11-12", "class 9-12", "class 11-pg",
                    "class 11-ug", "11-12", "senior secondary", "class 9-ug"),
    "Undergraduate": ("ug", "undergraduate", "bachelor", "class 11-ug", "class 9-ug", "graduation"),
    "Postgraduate": ("pg", "postgraduate", "post-grad", "m.phil", "phd", "class 11-pg"),
    "Diploma": ("diploma", "ug", "polytechnic"),
}

NATIONAL_JOB_HINTS = (
    "upsc", "ssc", "rrb", "railway", "nda", "cds", "ibps", "sbi", "rbi",
    "all india", "national", "union public", "staff selection",
)

SCHOLARSHIP_STATUSES = [
    ("saved", "Saved"),
    ("documents", "Documents in progress"),
    ("applied", "Applied"),
    ("result", "Result / closed"),
]


def parse_list(value):
    if not value:
        return []
    if isinstance(value, (list, tuple)):
        return [str(v).strip() for v in value if str(v).strip()]
    return [v.strip() for v in str(value).split(",") if v.strip()]


def profile_interests(profile):
    if not profile:
        return []
    raw = profile.get("interests") if hasattr(profile, "get") else profile["interests"]
    if not raw:
        return []
    if isinstance(raw, list):
        return raw
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return parse_list(raw)


def profile_subjects(profile):
    if not profile:
        return []
    raw = profile.get("subjects") if hasattr(profile, "get") else None
    if not raw:
        return []
    if isinstance(raw, list):
        return raw
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return parse_list(raw)


def profile_riasec(profile):
    if not profile:
        return []
    raw = profile.get("riasec_codes") if hasattr(profile, "get") else None
    if not raw:
        return []
    if isinstance(raw, list):
        return [str(x).upper()[:1] for x in raw]
    try:
        data = json.loads(raw)
        return [str(x).upper()[:1] for x in data]
    except (TypeError, ValueError):
        return [c for c in str(raw).upper() if c in "RIASEC"]


def _norm(text):
    return re.sub(r"\s+", " ", (text or "").lower()).strip()


def parse_flexible_date(value):
    if not value:
        return None
    text = str(value).strip()
    if not text or text in {"—", "-", "NA", "N/A", "tbd", "TBD"}:
        return None
    iso = text[:10]
    try:
        return datetime.date.fromisoformat(iso)
    except ValueError:
        pass
    for fmt in ("%d-%m-%Y", "%d/%m/%Y", "%d %b %Y", "%d %B %Y", "%b %d, %Y", "%B %d, %Y"):
        try:
            return datetime.datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    match = re.search(r"(\d{1,2})[/-](\d{1,2})[/-](\d{4})", text)
    if match:
        d, m, y = int(match.group(1)), int(match.group(2)), int(match.group(3))
        try:
            return datetime.date(y, m, d)
        except ValueError:
            return None
    return None


def education_compatible(profile_edu, sch_edu):
    if not sch_edu or not profile_edu:
        return True, "Education level not restricted"
    sch_l = _norm(sch_edu).replace("postgraduate", "pg").replace("undergraduate", "ug")
    if profile_edu.lower() in sch_l:
        return True, f"Listed for {sch_edu}"
    for token in EDU_TOKENS.get(profile_edu, ()):
        if token in sch_l:
            return True, f"{profile_edu} fits {sch_edu}"
    return False, f"For {sch_edu}; your level is {profile_edu}"


def _flag(profile, key):
    if not profile or key not in profile.keys():
        return False
    return bool(profile[key])


def scholarship_match_explanation(sch, profile):
    """Return {matched, passed, failed} explaining eligibility."""
    passed, failed = [], []
    if not profile:
        return {"matched": False, "passed": passed, "failed": ["No saved profile yet"]}

    ok, reason = education_compatible(profile.get("education_level"), sch.get("education_level"))
    (passed if ok else failed).append(reason)

    states = parse_list(sch.get("states"))
    if not states or states == ["All"]:
        passed.append("Open to all states")
    elif profile.get("state") in states:
        passed.append(f"Open in {profile.get('state')}")
    else:
        failed.append(f"Only for {', '.join(states)}")

    categories = parse_list(sch.get("categories"))
    profile_cat = profile.get("category")
    is_minority = _flag(profile, "is_minority") or profile_cat == "Minority"
    if not categories or categories == ["All"]:
        passed.append("Open to all categories")
    elif profile_cat in categories:
        passed.append(f"Open to {profile_cat}")
    elif "Minority" in categories and is_minority:
        passed.append("Open to minority students")
    else:
        failed.append(f"Only for {', '.join(categories)}")

    gender = sch.get("gender") or "All"
    if gender == "All":
        passed.append("Open to all genders")
    elif profile.get("gender") == gender:
        passed.append(f"Open to {gender} applicants")
    else:
        failed.append(f"Only for {gender} applicants")

    ceiling = sch.get("income_ceiling")
    income = profile.get("income_bracket")
    if not ceiling:
        passed.append("No income ceiling listed")
    elif not income:
        passed.append("Income ceiling not checked (add income to your profile)")
    elif int(income) <= int(ceiling):
        passed.append(f"Income within ₹{int(ceiling):,} ceiling")
    else:
        failed.append(f"Income above ₹{int(ceiling):,} ceiling")

    if sch.get("requires_disability"):
        if _flag(profile, "has_disability"):
            passed.append("For students with disability — matches your profile")
        else:
            failed.append("Requires a disability certificate")

    if sch.get("requires_minority") and not is_minority:
        failed.append("For minority-community students")

    return {"matched": not failed, "passed": passed, "failed": failed}


def scholarship_matches_profile(sch, profile):
    return scholarship_match_explanation(sch, profile)["matched"]


def stream_fits_cluster(stream, cluster):
    if not stream or stream == "undecided" or not cluster:
        return True
    allowed = STREAM_CLUSTERS.get(stream)
    if not allowed:
        return True
    return cluster in allowed


def _career_riasec_letters(career):
    raw = career.get("riasec") if hasattr(career, "get") else None
    if not raw:
        return []
    return [c for c in str(raw).upper() if c in "RIASEC"]


def score_career(career, profile):
    """Higher is a better recommendation. Returns (score, reasons)."""
    score = 0
    reasons = []
    interests = profile_interests(profile)
    cluster = career.get("cluster")
    if cluster and cluster in interests:
        score += 10
        reasons.append("Matches your interests")
    stream = (profile.get("stream") if profile else None) or ""
    if stream and stream_fits_cluster(stream, cluster):
        score += 6
        reasons.append("Fits your stream")
    elif stream and stream != "undecided" and cluster and not stream_fits_cluster(stream, cluster):
        score -= 4
        reasons.append("Different stream than you selected")

    letters = profile_riasec(profile)
    career_letters = _career_riasec_letters(career)
    overlap = set(letters) & set(career_letters)
    if overlap:
        score += 4 * len(overlap)
        reasons.append("Fits your interest-quiz type")

    if career.get("is_verified"):
        score += 3
    else:
        score -= 1

    edu = (profile.get("education_level") if profile else None) or ""
    if edu in {"Class 9-10", "Class 11-12"}:
        score += 1
        if (career.get("name") or "").lower() in {"professor", "lecturer"}:
            score -= 3
    return score, reasons


def recommended_career_rows(profile, db, limit=12, verified_only=True):
    if not profile:
        return []
    interests = profile_interests(profile)
    if not interests and not profile.get("stream") and not profile_riasec(profile):
        return []
    sql = "SELECT * FROM career_app_view"
    params = []
    if verified_only:
        sql += " WHERE is_verified = TRUE"
    rows = db.execute(sql, params).fetchall()
    ranked = []
    for row in rows:
        score, reasons = score_career(row, profile)
        if score <= 0:
            continue
        ranked.append((score, row, reasons))
    ranked.sort(key=lambda item: (-item[0], (item[1].get("name") or "")))
    out = []
    for score, row, reasons in ranked[:limit]:
        item = dict(row)
        item["match_score"] = score
        item["match_reasons"] = reasons
        out.append(item)
    return out


def recommended_career_ids(profile, db):
    return [r["career_id"] for r in recommended_career_rows(profile, db, limit=40)]


def is_national_job(job):
    blob = " ".join([
        str(job.get("commission") or ""),
        str(job.get("exam_kind") or ""),
        str(job.get("exam_name") or ""),
        str(job.get("department") or ""),
        str(job.get("job_title") or ""),
        str(job.get("state") or ""),
    ]).lower()
    if any(h in blob for h in NATIONAL_JOB_HINTS):
        return True
    state = (job.get("state") or "").strip().lower()
    return state in {"", "all", "all india", "india", "pan india"}


def gov_job_is_open(job, today=None):
    today = today or datetime.date.today()
    end = parse_flexible_date(job.get("apply_end_date"))
    if not end:
        return None
    return end >= today


def gov_job_eligibility(job, profile):
    """Soft eligibility notes. Never hides a national exam because of state."""
    passed, failed, notes = [], [], []
    if not profile:
        return {"eligible": None, "passed": passed, "failed": failed, "notes": ["Complete your profile to check fit"]}

    if is_national_job(job):
        passed.append("National exam — open regardless of home state")
    else:
        job_state = (job.get("state") or "").strip()
        if job_state and profile.get("state") and job_state.lower() not in {profile["state"].lower(), "all"}:
            if profile["state"].lower() not in job_state.lower():
                notes.append(f"Notification looks state-specific ({job_state}). Check domicile rules.")
            else:
                passed.append(f"State looks aligned with {profile['state']}")
        elif job_state:
            passed.append(f"State: {job_state}")

    qual = _norm(job.get("qualification"))
    edu = profile.get("education_level") or ""
    if qual:
        if edu in {"Class 9-10"} and any(x in qual for x in ("graduate", "graduation", "bachelor", "degree")):
            notes.append("Qualification looks graduate-level — treat as a long-term path")
        elif edu in {"Class 11-12"} and any(x in qual for x in ("graduate", "graduation", "bachelor")):
            notes.append("Usually after graduation — start preparing, apply later")
        elif "12" in qual or "intermediate" in qual or "10+2" in qual or "higher secondary" in qual:
            if edu in {"Class 11-12", "Undergraduate", "Postgraduate", "Diploma"}:
                passed.append("12th-pass level qualification")
        elif edu in {"Undergraduate", "Postgraduate"}:
            passed.append("Check the PDF for exact degree/subject rules")

    return {"eligible": not failed, "passed": passed, "failed": failed, "notes": notes}


def next_steps_for_profile(profile, lang="en"):
    if not profile:
        return None
    hi = lang == "hi"
    edu = profile.get("education_level") or ""
    interests = profile_interests(profile)
    stream = profile.get("stream") or ""
    steps = {"stream": None, "subjects": [], "actions": [], "career_tips": []}

    cluster_stream = {
        "tech": ("Science (PCM)", "Mathematics, Physics, Computer Science",
                 "Start JEE Main / CUET basics and a little coding (Python)." if not hi
                 else "JEE Main / CUET की तैयारी शुरू करें। Python की बेसिक कोडिंग सीखें।"),
        "science": ("Science (PCM/PCB)", "Physics, Chemistry, Maths/Biology",
                    "Start NEET or JEE prep alongside board work." if not hi
                    else "बोर्ड के साथ NEET या JEE की तैयारी शुरू करें।"),
        "engineering": ("Science (PCM)", "Mathematics, Physics, Chemistry",
                        "Plan JEE Main / state CET. Try a simple CAD or coding project." if not hi
                        else "JEE Main / स्टेट CET प्लान करें। छोटा CAD या कोडिंग प्रोजेक्ट आज़माएं।"),
        "healthcare": ("Science (PCB)", "Biology, Chemistry, Physics",
                       "Start NEET-UG prep and keep practicals strong." if not hi
                       else "NEET-UG की तैयारी शुरू करें। प्रैक्टिकल न छोड़ें।"),
        "business": ("Commerce", "Accountancy, Business Studies, Economics",
                     "Strengthen accounts. Look at CA Foundation / CUET B.Com." if not hi
                     else "अकाउंट्स मजबूत करें। CA Foundation / CUET B.Com देखें।"),
        "law": ("Arts or Commerce", "Political Science, Economics, English",
                "Begin CLAT-style legal reasoning and reading." if not hi
                else "CLAT जैसा लीगल रीजनिंग और रीडिंग शुरू करें।"),
        "social": ("Arts / Humanities", "Political Science, Sociology, Languages",
                   "Volunteer and look at B.A. / B.Ed / social-work paths." if not hi
                   else "वॉलंटियर करें। B.A. / B.Ed / सोशल वर्क पथ देखें।"),
        "creative": ("Arts, or any stream + portfolio", "Design, Fine Arts, or related electives",
                     "Start a portfolio. Check NID DAT / NIFT / CUET." if not hi
                     else "पोर्टफोलियो शुरू करें। NID DAT / NIFT / CUET देखें।"),
    }

    if stream and stream != "undecided":
        steps["stream"] = dict(STREAMS).get(stream, stream)

    if edu == "Class 9-10":
        if not interests:
            steps["actions"].append(
                "Pick a stream after Class 10 — Science, Commerce, or Arts — based on subjects you enjoy."
                if not hi else "क्लास 10 के बाद स्ट्रीम चुनें — साइंस, कॉमर्स या आर्ट्स।"
            )
        else:
            for c in interests:
                if c in cluster_stream:
                    s, subj, action = cluster_stream[c]
                    if not steps["stream"]:
                        steps["stream"] = s
                    steps["subjects"].append(subj)
                    steps["actions"].append(action)
        steps["career_tips"] = [
            "Class 10 is for choosing a stream, not applying to graduate jobs."
            if not hi else "क्लास 10 में स्ट्रीम चुनें — ग्रेजुएट नौकरी अभी नहीं।",
            "Talk to a teacher, then lock the stream. Exam coaching comes after that."
            if not hi else "शिक्षक से बात करें, फिर स्ट्रीम लॉक करें।",
        ]
        return steps

    if edu == "Class 11-12":
        if not interests:
            steps["actions"].append(
                "Keep exam prep going for your stream and shortlist colleges."
                if not hi else "अपनी स्ट्रीम के एग्जाम की तैयारी जारी रखें और कॉलेज शॉर्टलिस्ट करें।"
            )
        else:
            for c in interests:
                if c in cluster_stream:
                    steps["actions"].append(cluster_stream[c][2])
            steps["actions"].append(
                "Use the exam calendar and start a scholarship shortlist this year."
                if not hi else "एग्जाम कैलेंडर देखें और इस साल स्कॉलरशिप शॉर्टलिस्ट बनाएं।"
            )
        steps["career_tips"] = [
            "Class 11–12 is the main entrance-exam window."
            if not hi else "क्लास 11–12 एग्जाम तैयारी का मुख्य समय है।",
            "Add one practical project or internship alongside books."
            if not hi else "किताबों के साथ एक प्रैक्टिकल प्रोजेक्ट या इंटर्नशिप जोड़ें।",
        ]
        return steps

    if edu == "Undergraduate":
        steps["actions"].append(
            "Do internships, keep a portfolio/GitHub, and watch campus plus government exam calendars."
            if not hi else "इंटर्नशिप करें, पोर्टफोलियो/GitHub रखें, और कैंपस व सरकारी एग्जाम कैलेंडर देखें।"
        )
        steps["actions"].append(
            "Check scholarships still open at UG level and document readiness."
            if not hi else "UG स्तर की खुली स्कॉलरशिप और दस्तावेज़ तैयार रखें।"
        )
        steps["career_tips"] = [
            "Skills and internships matter more than collecting extra degrees right now."
            if not hi else "अभी स्किल्स और इंटर्नशिप अतिरिक्त डिग्री से ज़्यादा मायने रखते हैं।"
        ]
        return steps

    if edu == "Postgraduate":
        steps["actions"].append(
            "Choose research, industry, or a professional exam (NET, GATE, CFA, judiciary) and work backwards."
            if not hi else "रिसर्च, इंडस्ट्री या प्रोफेशनल एग्जाम (NET, GATE, CFA, ज्यूडिशियरी) चुनें।"
        )
        return steps

    if edu == "Diploma":
        steps["actions"].append(
            "Map diploma skills to technician/junior roles and check lateral entry into a bachelor's."
            if not hi else "डिप्लोमा स्किल्स को जूनियर भूमिकाओं से जोड़ें और लेटरल एंट्री जाँचें।"
        )
        return steps

    steps["actions"].append(
        "Keep your roadmap updated as your education level changes."
        if not hi else "जैसे-जैसे पढ़ाई आगे बढ़े, रोडमैप अपडेट करते रहें।"
    )
    return steps


RIASEC_QUESTIONS = [
    ("R1", "R", "I like fixing, building, or working with tools and machines.",
     "मुझे चीज़ें ठीक करना, बनाना या औज़ार/मशीन से काम करना पसंद है।"),
    ("R2", "R", "I would rather be outdoors or in a workshop than at a desk all day.",
     "पूरे दिन डेस्क के बजाय बाहर या वर्कशॉप में काम अच्छा लगता है।"),
    ("I1", "I", "I like experiments and figuring out why something works.",
     "मुझे प्रयोग करना और यह समझना पसंद है कि कोई चीज़ क्यों काम करती है।"),
    ("I2", "I", "I enjoy puzzles, research, or analysing data.",
     "पहेलियाँ, रिसर्च या डेटा जाँचना मुझे अच्छा लगता है।"),
    ("A1", "A", "I like drawing, writing, design, music, or making videos.",
     "मुझे चित्रकला, लेखन, डिज़ाइन, संगीत या वीडियो बनाना पसंद है।"),
    ("A2", "A", "I want work where I can invent or express my own ideas.",
     "मैं ऐसा काम चाहता/चाहती हूँ जिसमें अपने विचार बना सकूँ।"),
    ("S1", "S", "I like helping, teaching, or listening to people.",
     "मुझे लोगों की मदद, पढ़ाना या उनकी बात सुनना पसंद है।"),
    ("S2", "S", "I care about health, education, or community work.",
     "स्वास्थ्य, शिक्षा या सामुदायिक काम मेरे लिए महत्वपूर्ण हैं।"),
    ("E1", "E", "I like leading a group, debating, or starting a project.",
     "मुझे समूह चलाना, बहस करना या प्रोजेक्ट शुरू करना पसंद है।"),
    ("E2", "E", "Selling an idea or running something of my own sounds exciting.",
     "किसी आइडिया को बेचना या अपना काम चलाना रोमांचक लगता है।"),
    ("C1", "C", "I like organising files, numbers, rules, or step-by-step work.",
     "फाइल, संख्या, नियम या चरणबद्ध काम व्यवस्थित करना अच्छा लगता है।"),
    ("C2", "C", "I am careful with details and prefer clear instructions.",
     "मैं विवरणों का ध्यान रखता/रखती हूँ और साफ़ निर्देश पसंद करता/करती हूँ।"),
]


def score_riasec(answers):
    """answers: dict question_id -> 'yes'|'no' or truthy."""
    tallies = {k: 0 for k in "RIASEC"}
    for qid, letter, _en, _hi in RIASEC_QUESTIONS:
        val = answers.get(qid)
        if val in (True, "yes", "on", "1", 1, "true", "True"):
            tallies[letter] += 1
    ranked = sorted(tallies.items(), key=lambda kv: (-kv[1], kv[0]))
    top = [letter for letter, n in ranked if n > 0][:3]
    return top, tallies
