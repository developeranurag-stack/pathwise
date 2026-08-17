import os
import json
import re
import datetime
from functools import wraps

from flask import Flask, g, request, redirect, url_for, render_template, session, flash, jsonify, send_file
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

import db as dbmod
from seed_data import CAREERS, SCHOLARSHIPS, INTEREST_CLUSTERS
import scraper
# assistant is imported lazily inside the /assistant routes so the app can start
# without the optional 'openai' package (see requirements.txt and AGENTS.md)

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-key-change-in-production")
app.config["MAX_CONTENT_LENGTH"] = 32 * 1024 * 1024  # 32MB, generous for a scanned notification PDF

# Drop folder for the sibling pathwise-mcp project (see ../pathwise-mcp/CLAUDE.md) — PDFs placed
# here are picked up manually (or by instructing an MCP client) for `store_notification_pdf`
# which copies to stored_pdfs/ then extract + save_job_to_database into gov_job_notifications.
# We track successful MCP read by matching the original filename stem against stored local_pdf_path.
# Only works when both projects run on the same host.
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
        if career_count == 0:
            from seed_data import seed_careers
            seed_careers(conn, CAREERS)
            conn.commit()

        sch_count = conn.execute("SELECT COUNT(*) AS n FROM scholarships").fetchone()["n"]
        if sch_count == 0:
            from seed_data import seed_scholarships
            seed_scholarships(conn, SCHOLARSHIPS)
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


@app.context_processor
def inject_user():
    return dict(current_user=current_user())


# ----------------- MATCHING LOGIC -----------------

def parse_list(value):
    return [v.strip() for v in value.split(",")] if value else []


def scholarship_matches_profile(sch, profile):
    """Returns True if the scholarship's eligibility criteria fit the student's profile."""
    if not profile:
        return False

    edu = profile["education_level"]
    if sch["education_level"] and edu:
        # Loose containment match since ranges like "Class 9-12" vs "Class 11-12" overlap in spirit
        if edu not in sch["education_level"] and sch["education_level"] not in edu:
            level_tokens = {"Class 9-10": "Class 9", "Class 11-12": "Class 1", "Undergraduate": "UG",
                             "Postgraduate": "PG", "Diploma": "UG"}
            token = level_tokens.get(edu)
            if not token or token not in sch["education_level"]:
                return False

    states = parse_list(sch["states"])
    if states and states != ["All"] and profile["state"] not in states:
        return False

    categories = parse_list(sch["categories"])
    if categories and categories != ["All"] and profile["category"] not in categories:
        return False

    if sch["gender"] and sch["gender"] != "All" and profile["gender"] != sch["gender"]:
        return False

    if sch["income_ceiling"] and profile["income_bracket"]:
        if profile["income_bracket"] > sch["income_ceiling"]:
            return False

    return True


def recommended_career_ids(profile, db):
    if not profile or not profile["interests"]:
        return []
    interests = json.loads(profile["interests"])
    if not interests:
        return []
    placeholders = ",".join("?" for _ in interests)
    rows = db.execute(f"SELECT career_id FROM career_app_view WHERE cluster IN ({placeholders})", interests).fetchall()
    return [r["career_id"] for r in rows]


def next_steps_for_profile(profile, db):
    if not profile:
        return None
    edu = profile.get("education_level", "")
    interests = json.loads(profile["interests"]) if profile.get("interests") else []
    steps = {"stream": None, "subjects": [], "actions": [], "career_tips": []}

    if edu == "Class 9-10":
        if not interests:
            steps["actions"].append("अपनी रुचियों के आधार पर स्ट्रीम चुनें — साइंस, कॉमर्स या आर्ट्स।")
            return steps

        cluster_stream = {
            "tech": ("Science (PCM)", "मैथमैटिक्स, फिजिक्स, कंप्यूटर साइंस/ईटी", "जीई जेई मेन, CUET, या स्टेट CET की तैयारी शुरू करें। कोडिंग बासिक्स सीखें (Python/HTML-CSS)।"),
            "science": ("Science (PCM/PCB)", "फिजिक्स, केमिस्ट्री, बायोलॉजी/गणित", "NEET/JEE की तैयारी के लिए कोचिंग या सेल्फ-स्टडी शुरू करें। प्रयोगात्मक कौशल बनाए रखें।"),
            "engineering": ("Science (PCM)", "मैथमैटिक्स, फिजिक्स, केमिस्ट्री", "JEE Main/Advanced की तैयारी शुरू करें। स्केचिंग और ऑटोकैड बेसिक सीखें।"),
            "healthcare": ("Science (PCB)", "बायोलॉजी, केमिस्ट्री, फिजिक्स", "NEET-UG की तैयारी शुरू करें। मेडिकल कोचिंग या बोर्ड के साथ एलनप्लस रजिस्टर करें।"),
            "business": ("Commerce", "अकाउंटेंसी, बिजनेस स्टडीज, इकॉनॉमिक्स", "CS Foundation या बोर्ड के साथ अकाउंटेंसी बेसिक सीखें।"),
            "law": ("Arts/Commerce", "पोलिटिकल साइंस, इकॉनॉमिक्स, इंग्लिश", "CLAT के लिए लेगल रीजनिंग और जीजी स्टडी शुरू करें।"),
            "social": ("Arts/Humanities", "पोलिटिकल साइंस, सोशल साइंस, सांस्कृतिक अध्ययन", "B.Ed या सामाजिक कार्य पाठ्यक्रमों की जांच करें। वॉलंटियर वर्क शुरू करें।"),
            "creative": ("Arts/Commerce", "ग्राफिक डिजाइन, फाइन आर्ट्स, इंटीरियर डिजाइन बेसिक्स", "NID DAT/NIFT के लिए पोर्टफोलियो शुरू करें। स्केचिंग और कन्वेंशनल टूल्स सीखें।"),
        }

        tips = []
        for c in interests:
            if c in cluster_stream:
                s, subj, action = cluster_stream[c]
                if not steps["stream"]:
                    steps["stream"] = s
                steps["subjects"].append(subj)
                steps["actions"].append(action)
                tips.append(f"{c}: {s} स्ट्रीम चुनें")
            else:
                steps["actions"].append(f"{c} के लिए उपयुक्त स्ट्रीम और एग्जाम की जांच करें।")

        steps["career_tips"] = [
            "अभी क्लास 10 में हो — स्ट्रीम चुनने से पहले हर ऑप्शन के बारे में जानें।",
            "किसी सेनियर या कोच से परामर्श लें, फिर स्ट्रीम फिक्स करें।",
            "स्ट्रीम चुनने के बाद ही टारगेटेड एग्जाम की तैयारी शुरू करें।"
        ]
        return steps

    if edu == "Class 11-12":
        if not interests:
            steps["actions"].append("अपनी स्ट्रीम के एग्जाम की तैयारी फुल-स्पीड जारी रखें।")
            steps["actions"].append("काउंसलिंग लें और किसी मेनटर से अपनी रोडमैप बनाएं।")
            return steps

        cluster_action = {
            "tech": ("जीई जेई मेन/एडवांस्ड या CUET पर तैयारी जारी रखें। साइड में Python/Web बेसिक प्रैक्टिस करें।", "B.Tech/BCA/B.Sc CS के लिए कॉलेज चयन और स्कॉलरशिप की जांच शुरू करें।"),
            "science": ("NEET/JEE की तैयारी फुल-फोकस में जारी रखें। सभी सब्जेक्ट्स की रिवीजन शेड्यूल बनाएं।", "कोचिंग या ऑनलाइन कोर्स की फीडबैक लें। रिवीजन और मॉक टेस्ट की आदत डालें।"),
            "engineering": ("JEE Main/Advanced या स्टेट CET की तैयारी बढ़ाएं। प्रैक्टिकल प्रोजेक्ट्स (ऑटोकैड/कोडिंग) शुरू करें।", "Polytechnic/Engineering कॉलेज की शॉर्टलिस्ट बनाएं।"),
            "healthcare": ("NEET-UG की तैयारी फाइनल स्पर्श में लाएं। बायोलॉजी/केमिस्ट्री के प्रैक्टिकल्स नज़रअंदाज न करें।", "मेडिकल कॉलेज के कटऑफ और सीट ऑलोटमेंट की जांच करें।"),
            "business": ("कॉमर्स की गड़न मजबूत करें — अकाउंटेंसी, बिजनेस स्टडीज, इकॉनॉमिक्स। CS Foundation/Executive की तैयारी शुरू करें।", "B.Com/BBA/BMS कॉलेज की जांच करें। शॉर्टलिस्ट और एडमिशन प्रोसेस शुरू करें।"),
            "law": ("CLAT/AILET की तैयारी बढ़ाएं। लेगल रीजनिंग, इंग्लिश और जीजी दैनिक प्रैक्टिस करें।", "5-year integrated LLB कॉलेज की शॉर्टलिस्ट बनाएं।"),
            "social": ("Humanities सब्जेक्ट्स की गहराई से पढ़ाई करें। सामाजिक कार्य/रिसर्च प्रोजेक्ट्स शुरू करें।", "B.A/B.Ed/सोशल वर्क कॉर्स की जांच करें। वॉलंटियर/इंटर्नशिप के लिए NGO से जुड़ें।"),
            "creative": ("पोर्टफोलियो बनाना शुरू करें। NID DAT/NIFT/JEE Main Paper 2 की तैयारी जारी रखें।", "डिजाइन स्कूल/कॉलेज की एडमिशन गाइड बनाएं। फ्रीलेंसिंग/इंटर्नशिप के लिए प्लेटफॉर्म जांचें।"),
        }
        for c in interests:
            if c in cluster_action:
                prep, next_step = cluster_action[c]
                steps["actions"].append(prep)
                steps["actions"].append(next_step)
            else:
                steps["actions"].append(f"{c} के लिए उपयुक्त UG कॉर्स और एग्जाम की जांच करें।")

        steps["career_tips"] = [
            "क्लास 11-12 का समय एग्जाम की तैयारी का सबसे महत्वपूर्ण चरण है।",
            "केवल बुक्स से नहीं, प्रैक्टिकल प्रोजेक्ट्स/इंटर्नशिप भी करें।",
            "काउंसलिंग से अपनी रोडमैप लगातार अपडेट करें।"
        ]
        return steps

    if edu == "Undergraduate":
        if not interests:
            steps["actions"].append("अपनी स्पेशलाइजेशन या इंटर्नशिप के लिए प्लान बनाएं।")
            return steps

        cluster_action = {
            "tech": ("FULL STACK / DATA / ML इंटर्नशिप के लिए आवेदन करें। GitHub/Portfolio अपडेट करें।", "Google Summer of Code, Hackathons, और Freelancing प्रोजेक्ट्स शुरू करें।"),
            "science": ("रिसर्च इंटर्नशिप (DRDO/ICMR/जीआईएस) या लैब असिस्टेंटशिप के लिए अप्लाई करें।", "रेसर्च पेपर पब्लिश करने और कॉन्फ्रेंस में प्रेजेंट करने की कोशिश करें।"),
            "engineering": ("इंटर्नशिप (स्टैग) और प्रैक्टिकल प्रोजेक्ट्स बढ़ाएं। Core/IT कंपनियों में अप्लाई करें।", "AutoCAD, CATIA, सोलर/रिन्यूएबल प्रोजेक्ट्स जोड़ें।"),
            "healthcare": ("हॉस्पिटल इंटर्नशिप, रिसर्च असिस्टेंट या फ्रीलेंसिंग के लिए आवेदन करें।", "रजिस्ट्रेशन/लाइसेंसिंग एग्जाम (जैसे RCI, Pharmacy Council) की जांच करें।"),
            "business": ("स्टार्टअप इंटर्नशिप, कैंपस प्लेसमेंट प्रिप, या CA/CS की रजिस्ट्रेशन करें।", "बिजनेस प्लान प्रतियोगिताओं और शेयर मार्केट प्रैक्टिस शुरू करें।"),
            "law": ("लॉ फर्म/जज मंथली/CLAT PG/जूडिशियरी रिसर्च इंटर्नशिप के लिए अप्लाई करें।", "मॉक ट्रायल, मोट मोट केस स्टडी और लेगल राइटिंग प्रैक्टिस बढ़ाएं।"),
            "social": ("शिक्षा/Social Work NGO इंटर्नशिप, रिसर्च प्रोजेक्ट्स या B.Ed प्रिप करें।", "पर्यावरण/महिला/बाल कल्याण के प्लेटफॉर्म से जुड़ें।"),
            "creative": ("डिजाइन स्टूडियो/एजेंसी इंटर्नशिप, फ्रीलेंसिंग गिग्स और पोर्टफोलियो अपडेट करें।", "Adobe Suite/Canva/वीडियो एडिटिंग प्रॉफिशिएंसी बढ़ाएं।"),
        }
        for c in interests:
            if c in cluster_action:
                prep, next_step = cluster_action[c]
                steps["actions"].append(prep)
                steps["actions"].append(next_step)
            else:
                steps["actions"].append(f"{c} फील्ड में इंटर्नशिप और प्रैक्टिकल प्रोजेक्ट्स शुरू करें।")

        steps["career_tips"] = [
            "यूनिटेक्स्ट का समय स्किल्स बिल्ड करने का सबसे अच्छा मौका है।",
            "नट वर्किंग प्रोजेक्ट्स बनाएं — ये प्लेसमेंट में ज्यादा मदद करेंगे।",
            "सर्टिफिकेशन कोर्स (Coursera/Google/Meta) करके रेज्यूमे बढ़ाएं।"
        ]
        return steps

    if edu == "Postgraduate":
        steps["actions"].append("अपनी स्पेशलाइजेशन (Research/Industry/Management) के लिए रोडमैप तैयार करें।")
        steps["actions"].append("सर्टिफिकेशन (जैसे PMP, CFA, GATE, NET) या फ्रेशनल कोर्स की तैयारी शुरू करें।")
        steps["actions"].append("नेटवर्किंग बढ़ाएं — कॉन्फ्रेंस, लिंक्डइन, इंडस्ट्री मीटअप्स में शामिल हों।")
        steps["career_tips"] = [
            "पोस्टग्रेजुएट से पहले या साथ ही इंडस्ट्री एक्सपोजर ज़रूरी है।",
            "रिसर्च/प्रैक्टिकल प्रोजेक्ट्स हाइलाइट करके प्लेसमेंट या फुर्ती पदों के लिए तैयार रहें।"
        ]
        return steps

    if edu == "Diploma":
        steps["actions"].append("अपनी डिप्लोमा स्पेशलाइजेशन के अनुकूल जॉब रोले की लिस्ट बनाएं।")
        steps["actions"].append("प्रैक्टिकल ट्रेनिंग/इंटर्नशिप के लिए स्थानीय इंडस्ट्री/गवर्नमेंट योजनाओं की जांच करें।")
        steps["actions"].append("अगर पढ़ाई जारी रखना है, तो लेटरल एंट्री से बैचलर डिग्री की जांच करें।")
        steps["career_tips"] = [
            "डिप्लोमा हाथ में है — स्किल्स की तरफ ज़्यादा फोकस करें।",
            "जॉब ओपनिंग्स (गवर्नमेंट/प्राइवेट) में अप्लाई करने की आदत डालें।"
        ]
        return steps

    steps["actions"].append("अपने करियर रोडमैप पर नज़र रखें और नए स्किल्स सीखते रहें।")
    return steps


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

@app.route("/onboarding", methods=["GET", "POST"])
@login_required
def onboarding():
    if request.method == "POST":
        education_level = request.form.get("education_level")
        state = request.form.get("state")
        category = request.form.get("category")
        gender = request.form.get("gender")
        income_bracket = request.form.get("income_bracket") or None
        interests = request.form.getlist("interests")

        db = get_db()
        db.execute(
            """INSERT INTO profiles (user_id, education_level, state, category, gender,
               income_bracket, interests)
               VALUES (?,?,?,?,?,?,?)
               ON CONFLICT(user_id) DO UPDATE SET
                 education_level=excluded.education_level, state=excluded.state,
                 category=excluded.category, gender=excluded.gender,
                 income_bracket=excluded.income_bracket, interests=excluded.interests""",
            (session["user_id"], education_level, state, category, gender,
             int(income_bracket) if income_bracket else None, json.dumps(interests)),
        )
        db.commit()
        flash("Profile saved! Here's what we recommend for you.", "success")
        return redirect(url_for("dashboard"))

    profile = current_profile()
    return render_template(
        "onboarding.html", profile=profile, clusters=INTEREST_CLUSTERS,
        education_levels=EDUCATION_LEVELS, categories=CATEGORIES, states=INDIAN_STATES,
        current_interests=json.loads(profile["interests"]) if profile and profile["interests"] else [],
    )


# ----------------- ROUTES: CAREERS -----------------

@app.route("/careers")
def careers_list():
    db = get_db()
    cluster_filter = request.args.get("cluster", "")
    if cluster_filter:
        rows = db.execute("SELECT * FROM career_app_view WHERE cluster = ? ORDER BY name", (cluster_filter,)).fetchall()
    else:
        rows = db.execute("SELECT * FROM career_app_view ORDER BY name").fetchall()

    saved_ids = set()
    profile = current_profile()
    recommended_ids = set(recommended_career_ids(profile, db)) if session.get("user_id") else set()
    if session.get("user_id"):
        saved_rows = db.execute("SELECT career_id FROM saved_careers WHERE user_id = ?", (session["user_id"],)).fetchall()
        saved_ids = {r["career_id"] for r in saved_rows}

    return render_template(
        "careers_list.html", careers=rows, clusters=INTEREST_CLUSTERS,
        active_cluster=cluster_filter, saved_ids=saved_ids, recommended_ids=recommended_ids,
    )


@app.route("/careers/<slug>")
def career_detail(slug):
    db = get_db()
    career = db.execute("SELECT * FROM career_app_view WHERE slug = ?", (slug,)).fetchone()
    if not career:
        flash("Career not found.", "error")
        return redirect(url_for("careers_list"))

    is_saved = False
    if session.get("user_id"):
        row = db.execute(
            "SELECT 1 FROM saved_careers WHERE user_id = ? AND career_id = ?",
            (session["user_id"], career["career_id"]),
        ).fetchone()
        is_saved = row is not None

    return render_template("career_detail.html", career=career, is_saved=is_saved, profile=current_profile())


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
        flash("Added to your roadmap.", "success")
    db.commit()
    return redirect(request.referrer or url_for("careers_list"))


# ----------------- ROUTES: SCHOLARSHIPS -----------------

@app.route("/scholarships")
def scholarships_list():
    db = get_db()
    type_filter = request.args.get("type", "")
    show_matches_only = request.args.get("matches") == "1"

    if type_filter:
        rows = db.execute("SELECT * FROM scholarships WHERE type = ? ORDER BY deadline", (type_filter,)).fetchall()
    else:
        rows = db.execute("SELECT * FROM scholarships ORDER BY deadline").fetchall()

    profile = current_profile()
    matched_ids = set()
    if profile:
        for r in rows:
            if scholarship_matches_profile(r, profile):
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
        show_matches_only=show_matches_only,
    )


@app.route("/scholarships/<int:scholarship_id>")
def scholarship_detail(scholarship_id):
    db = get_db()
    sch = db.execute("SELECT * FROM scholarships WHERE id = ?", (scholarship_id,)).fetchone()
    if not sch:
        flash("Scholarship not found.", "error")
        return redirect(url_for("scholarships_list"))

    profile = current_profile()
    is_match = scholarship_matches_profile(sch, profile) if profile else None

    is_saved = False
    if session.get("user_id"):
        row = db.execute(
            "SELECT 1 FROM saved_scholarships WHERE user_id = ? AND scholarship_id = ?",
            (session["user_id"], scholarship_id),
        ).fetchone()
        is_saved = row is not None

    return render_template("scholarship_detail.html", sch=sch, is_match=is_match, is_saved=is_saved)


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
        flash("Added to your roadmap.", "success")
    db.commit()
    return redirect(request.referrer or url_for("scholarships_list"))


# ----------------- ROUTES: GOVERNMENT JOB NOTIFICATIONS -----------------
# Populated out-of-band by the pathwise-mcp MCP server (see ../pathwise-mcp),
# which extracts these fields from official PDF notifications. Read-only here.

@app.route("/gov-jobs")
def gov_jobs_list():
    db = get_db()
    rows = db.execute("SELECT * FROM gov_job_notifications ORDER BY created_at DESC").fetchall()
    return render_template("gov_jobs_list.html", jobs=rows)


@app.route("/gov-jobs/<int:job_id>")
def gov_job_detail(job_id):
    db = get_db()
    job = db.execute("SELECT * FROM gov_job_notifications WHERE id = ?", (job_id,)).fetchone()
    if not job:
        flash("Job notification not found.", "error")
        return redirect(url_for("gov_jobs_list"))
    posts = db.execute("SELECT * FROM gov_job_posts WHERE notification_id = ? ORDER BY id", (job_id,)).fetchall()
    return render_template("gov_job_detail.html", job=job, posts=posts)


@app.route("/gov-jobs/<int:job_id>/pdf")
def gov_job_pdf(job_id):
    db = get_db()
    job = db.execute("SELECT local_pdf_path FROM gov_job_notifications WHERE id = ?", (job_id,)).fetchone()
    if not job or not job["local_pdf_path"] or not os.path.exists(job["local_pdf_path"]):
        flash("PDF not available for this notification.", "error")
        return redirect(url_for("gov_jobs_list"))
    return send_file(job["local_pdf_path"])


# ----------------- ROUTES: ADMIN -----------------

CAREER_FIELDS = ["slug", "name", "cluster", "description", "demand", "salary_min",
                  "salary_max", "skills", "ai_impact", "education_path", "exams"]
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


@app.route("/admin/gov-jobs")
@admin_required
def admin_gov_jobs_list():
    db = get_db()
    rows = db.execute(
        "SELECT id, job_title, local_pdf_path, created_at FROM gov_job_notifications ORDER BY created_at DESC"
    ).fetchall()
    processed_count = len(rows)

    # Map original filename stem -> list of matching saved jobs.
    # MCP's store_notification_pdf renames to {stem}_{mtime_ns}.pdf so we detect by prefix match on the stored copy.
    ingested = {}
    for r in rows:
        lp = r["local_pdf_path"] or ""
        if lp:
            b = os.path.basename(lp)
            if b.lower().endswith(".pdf"):
                noext = b[:-4]
                if "_" in noext:
                    cand, suf = noext.rsplit("_", 1)
                    if suf.isdigit():
                        ingested.setdefault(cand, []).append(
                            {"id": r["id"], "job_title": r["job_title"], "created_at": str(r["created_at"])[:19]}
                        )

    pending = []
    if os.path.isdir(GOV_JOB_UPLOAD_DIR):
        for name in sorted(os.listdir(GOV_JOB_UPLOAD_DIR)):
            path = os.path.join(GOV_JOB_UPLOAD_DIR, name)
            if os.path.isfile(path):
                stem = os.path.splitext(name)[0]
                matches = ingested.get(stem, [])
                pending.append({
                    "name": name,
                    "size": os.path.getsize(path),
                    "status": "processed" if matches else "pending",
                    "matches": matches,
                })
    return render_template("admin/gov_job_uploads.html", pending=pending, processed_count=processed_count)


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

    flash(f'"{filename}" uploaded to drop dir. Refresh /admin/gov-jobs to see if pathwise-mcp has read it (status changes to processed when a matching job appears in DB).', "success")
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

@app.route("/dashboard")
@login_required
def dashboard():
    db = get_db()
    profile = current_profile()

    saved_careers = db.execute(
        """SELECT v.* FROM career_app_view v
           JOIN saved_careers sc ON v.career_id = sc.career_id
           WHERE sc.user_id = ? ORDER BY v.name""",
        (session["user_id"],),
    ).fetchall()

    saved_scholarships = db.execute(
        """SELECT scholarships.* FROM scholarships
           JOIN saved_scholarships ON scholarships.id = saved_scholarships.scholarship_id
           WHERE saved_scholarships.user_id = ? ORDER BY scholarships.deadline""",
        (session["user_id"],),
    ).fetchall()

    recommended_careers = []
    matched_scholarships = []
    next_steps = None
    if profile:
        rec_ids = recommended_career_ids(profile, db)
        if rec_ids:
            placeholders = ",".join("?" for _ in rec_ids)
            recommended_careers = db.execute(
                f"SELECT * FROM career_app_view WHERE career_id IN ({placeholders}) ORDER BY name", rec_ids
            ).fetchall()

        all_scholarships = db.execute("SELECT * FROM scholarships ORDER BY deadline").fetchall()
        matched_scholarships = [s for s in all_scholarships if scholarship_matches_profile(s, profile)][:6]

        next_steps = next_steps_for_profile(profile, db)

    today = datetime.date.today().isoformat()

    return render_template(
        "dashboard.html", profile=profile, saved_careers=saved_careers,
        saved_scholarships=saved_scholarships, recommended_careers=recommended_careers,
        matched_scholarships=matched_scholarships, today=today,
        next_steps=next_steps,
    )


# ----------------- ROUTES: ASSISTANT -----------------

@app.route("/assistant")
@login_required
def assistant_page():
    return render_template(
        "assistant.html", history=session.get("assistant_history", []), profile=current_profile(),
    )


@app.route("/assistant/message", methods=["POST"])
@login_required
def assistant_message():
    data = request.get_json(silent=True) or {}
    user_message = (data.get("message") or "").strip()
    if not user_message:
        return jsonify({"error": "Message is required."}), 400

    db = get_db()
    history = session.get("assistant_history", [])
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

    session["assistant_history"] = new_history
    return jsonify({"reply": reply, "cards": cards})


@app.route("/assistant/reset", methods=["POST"])
@login_required
def assistant_reset():
    session.pop("assistant_history", None)
    return redirect(url_for("assistant_page"))


init_db()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
