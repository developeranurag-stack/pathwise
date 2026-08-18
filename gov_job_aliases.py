"""Data-driven aliases for Indian government-exam issuers.

Students type acronyms and exam brands ("cgpsc", "upsc cse", "ras"). Rows in
gov_job_notifications often store a full commission name, Hindi, a PDF
filename stem, or a single cadre post. expand_gov_job_query() bridges that gap
for search_gov_jobs — it is not a CGPSC special case.
"""
from __future__ import annotations

import json
import re
from pathlib import Path


def _issuer(
    code,
    name_en,
    name_hi=None,
    state=None,
    state_hi=None,
    url_hosts=None,
    aliases=None,
    exam_aliases=None,
    primary_exams=None,
    national=False,
):
    return {
        "code": code,
        "name_en": name_en,
        "name_hi": list(name_hi or []),
        "state": state,
        "state_hi": list(state_hi or []),
        "url_hosts": list(url_hosts or []),
        "aliases": list(aliases or []),
        "exam_aliases": {k: list(v) for k, v in (exam_aliases or {}).items()},
        "primary_exams": list(primary_exams or []),
        "national": bool(national),
    }


# Generic state-exam brands: expand phrases but do not force a single state.
GENERIC_EXAMS = {
    "pcs": [
        "pcs",
        "provincial civil service",
        "provincial civil services",
        "state service",
        "state service examination",
        "state civil service",
        "combined competitive",
        "combined competitive examination",
        "cce",
        "राज्य सेवा",
        "राज्य सेवा परीक्षा",
    ],
    "sse": [
        "sse",
        "state service",
        "state service examination",
        "state civil service",
        "राज्य सेवा",
        "राज्य सेवा परीक्षा",
    ],
    "cce": [
        "cce",
        "combined competitive",
        "combined competitive examination",
        "state service",
        "state service examination",
    ],
    "state service": [
        "state service",
        "state service examination",
        "state civil service",
        "राज्य सेवा",
        "राज्य सेवा परीक्षा",
        "sse",
    ],
    "group 1": ["group 1", "group-1", "group i", "group1"],
    "group 2": ["group 2", "group-2", "group ii", "group2"],
    "group 4": ["group 4", "group-4", "group iv", "group4"],
}

# Exam brands that belong to one issuer even without the commission name.
BOUND_EXAMS = {
    "cse": "UPSC",
    "ias": "UPSC",
    "ips": "UPSC",
    "ifs": "UPSC",
    "ifos": "UPSC",
    "nda": "UPSC",
    "cds": "UPSC",
    "capf": "UPSC",
    "cms": "UPSC",
    "ese": "UPSC",
    "ies": "UPSC",
    "cgl": "SSC",
    "chsl": "SSC",
    "mts": "SSC",
    "cpo": "SSC",
    "ntpc": "RRB",
    "alp": "RRB",
    "ras": "RPSC",
    "rts": "RPSC",
    "rajyaseva": "MPSC",
    "wbcs": "WBPSC",
    "vyapam": "MPPSC",
    "peb": "MPPSC",
    "hcs": "HPSC",
    "kas": "KPSC",
}

# Devanagari spellings of Latin exam/commission acronyms (letter-by-letter).
DEVANAGARI_TO_LATIN = {
    "यूपीएससी": "upsc",
    "एसएससी": "ssc",
    "सीजीपीएससी": "cgpsc",
    "एमपीपीएससी": "mppsc",
    "यूपीपीएससी": "uppsc",
    "यूकेपीएससी": "ukpsc",
    "बीपीएससी": "bpsc",
    "जेपीएससी": "jpsc",
    "आरपीएससी": "rpsc",
    "एचपीएससी": "hpsc",
    "पीपीएससी": "ppsc",
    "जीपीएससी": "gpsc",
    "एमपीएससी": "mpsc",
    "एपीएससी": "apsc",
    "ओपीएससी": "opsc",
    "डब्ल्यूपीएससी": "wbpsc",
    "डब्लूबीपीएससी": "wbpsc",
    "टीएनपीएससी": "tnpsc",
    "एपीपीएससी": "appsc",
    "टीएसपीएससी": "tspsc",
    "केपीएससी": "kpsc",
    "एचपीपीएससी": "hppsc",
    "जेकेपीएससी": "jkpsc",
    "आरआरबी": "rrb",
    "आईबीपीएस": "ibps",
    "सीएसई": "cse",
    "सीजीएल": "cgl",
    "एनडीए": "nda",
    "सीडीएस": "cds",
    "पीसीएस": "pcs",
    "आरएएस": "ras",
    "आईएएस": "ias",
    "आईपीएस": "ips",
    "सीएचएसएल": "chsl",
    "सीसीई": "cce",
}

_STATE_SERVICE_PHRASES = [
    "state service examination",
    "state service",
    "state civil service",
    "राज्य सेवा परीक्षा",
    "राज्य सेवा",
    "cce",
    "sse",
]

ISSUERS = [
    # ----- National -----
    _issuer(
        "UPSC",
        "Union Public Service Commission",
        name_hi=["संघ लोक सेवा आयोग"],
        url_hosts=["upsconline.nic.in", "upsc.gov.in"],
        aliases=["upsc"],
        exam_aliases={
            "cse": [
                "civil services examination",
                "civil services",
                "cse",
                "ias",
                "ips",
                "ifs",
                "ifos",
            ],
            "ese": ["engineering services examination", "engineering services", "ese", "ies"],
            "nda": ["national defence academy", "nda na", "nda"],
            "cds": ["combined defence services", "cds"],
            "capf": ["central armed police forces", "capf", "assistant commandant"],
            "cms": ["combined medical services", "cms"],
        },
        primary_exams=["cse"],
        national=True,
    ),
    _issuer(
        "SSC",
        "Staff Selection Commission",
        name_hi=["कर्मचारी चयन आयोग"],
        url_hosts=["ssc.gov.in", "ssc.nic.in"],
        aliases=["ssc"],
        exam_aliases={
            "cgl": ["combined graduate level", "cgl"],
            "chsl": ["combined higher secondary level", "chsl"],
            "mts": ["multi tasking staff", "multi-tasking staff", "mts"],
            "gd": ["constable gd", "general duty", "ssc gd"],
            "cpo": ["central police organisation", "si cpo", "cpo"],
            "je": ["junior engineer", "ssc je"],
            "stenographer": ["stenographer"],
        },
        primary_exams=["cgl"],
        national=True,
    ),
    _issuer(
        "RRB",
        "Railway Recruitment Board",
        name_hi=["रेलवे भर्ती बोर्ड"],
        url_hosts=["rrbcdg.gov.in", "indianrailways.gov.in"],
        aliases=["rrb", "rrc", "railway", "railways", "रेलवे"],
        exam_aliases={
            "ntpc": ["non technical popular categories", "ntpc"],
            "group_d": ["group d", "group-d", "level 1"],
            "alp": ["assistant loco pilot", "alp"],
            "technician": ["technician"],
        },
        primary_exams=["ntpc"],
        national=True,
    ),
    _issuer(
        "IBPS",
        "Institute of Banking Personnel Selection",
        name_hi=["बैंकिंग कार्मिक चयन संस्थान"],
        url_hosts=["ibps.in"],
        aliases=["ibps"],
        exam_aliases={
            "po": ["probationary officer", "ibps po"],
            "clerk": ["ibps clerk", "clerk"],
            "so": ["specialist officer", "ibps so"],
        },
        primary_exams=["po"],
        national=True,
    ),
    _issuer(
        "SBI",
        "State Bank of India",
        name_hi=["भारतीय स्टेट बैंक"],
        url_hosts=["sbi.co.in", "bank.sbi"],
        aliases=["sbi"],
        exam_aliases={
            "po": ["probationary officer", "sbi po"],
            "clerk": ["sbi clerk", "junior associate"],
            "so": ["sbi so", "specialist officer"],
        },
        primary_exams=["po"],
        national=True,
    ),
    _issuer(
        "RBI",
        "Reserve Bank of India",
        name_hi=["भारतीय रिज़र्व बैंक", "भारतीय रिजर्व बैंक"],
        url_hosts=["rbi.org.in"],
        aliases=["rbi"],
        exam_aliases={
            "grade_b": ["grade b", "rbi grade b"],
            "assistant": ["rbi assistant"],
        },
        primary_exams=["grade_b"],
        national=True,
    ),
    # ----- State PSCs -----
    _issuer(
        "CGPSC",
        "Chhattisgarh Public Service Commission",
        name_hi=["छत्तीसगढ़ लोक सेवा आयोग", "छत्तीसगढ लोक सेवा आयोग"],
        state="Chhattisgarh",
        state_hi=["छत्तीसगढ़", "छत्तीसगढ"],
        url_hosts=["psc.cg.gov.in", "cgpsc.cg.gov.in"],
        aliases=["cgpsc"],
        exam_aliases={
            "sse": list(_STATE_SERVICE_PHRASES),
            "ses": ["state engineering service", "राज्य अभियांत्रिकी सेवा", "ses"],
        },
        primary_exams=["sse"],
    ),
    _issuer(
        "MPPSC",
        "Madhya Pradesh Public Service Commission",
        name_hi=["मध्य प्रदेश लोक सेवा आयोग"],
        state="Madhya Pradesh",
        state_hi=["मध्य प्रदेश", "मध्यप्रदेश"],
        url_hosts=["mppsc.nic.in", "mppsc.mp.gov.in"],
        aliases=["mppsc"],
        exam_aliases={
            "sse": _STATE_SERVICE_PHRASES,
            "vyapam": ["vyapam", "peb", "professional examination board", "व्यापम"],
        },
        primary_exams=["sse"],
    ),
    _issuer(
        "UPPSC",
        "Uttar Pradesh Public Service Commission",
        name_hi=["उत्तर प्रदेश लोक सेवा आयोग"],
        state="Uttar Pradesh",
        state_hi=["उत्तर प्रदेश", "उत्तरप्रदेश"],
        url_hosts=["uppsc.up.nic.in"],
        aliases=["uppsc"],
        exam_aliases={
            "pcs": [
                "pcs",
                "provincial civil service",
                "uppcs",
                "up pcs",
            ]
            + _STATE_SERVICE_PHRASES,
            "ro_aro": ["ro aro", "review officer", "assistant review officer"],
        },
        primary_exams=["pcs"],
    ),
    _issuer(
        "UKPSC",
        "Uttarakhand Public Service Commission",
        name_hi=["उत्तराखंड लोक सेवा आयोग", "उत्तराखण्ड लोक सेवा आयोग"],
        state="Uttarakhand",
        state_hi=["उत्तराखंड", "उत्तराखण्ड"],
        url_hosts=["ukpsc.gov.in"],
        aliases=["ukpsc", "ukpcs"],
        exam_aliases={"pcs": ["pcs", "ukpcs"] + _STATE_SERVICE_PHRASES},
        primary_exams=["pcs"],
    ),
    _issuer(
        "BPSC",
        "Bihar Public Service Commission",
        name_hi=["बिहार लोक सेवा आयोग"],
        state="Bihar",
        state_hi=["बिहार"],
        url_hosts=["bpsc.bih.nic.in", "bpsc.bihar.gov.in"],
        aliases=["bpsc"],
        exam_aliases={"cce": ["cce", "combined competitive examination"] + _STATE_SERVICE_PHRASES},
        primary_exams=["cce"],
    ),
    _issuer(
        "JPSC",
        "Jharkhand Public Service Commission",
        name_hi=["झारखंड लोक सेवा आयोग", "झारखण्ड लोक सेवा आयोग"],
        state="Jharkhand",
        state_hi=["झारखंड", "झारखण्ड"],
        url_hosts=["jpsc.gov.in"],
        aliases=["jpsc"],
        exam_aliases={"cce": ["cce", "combined competitive examination"] + _STATE_SERVICE_PHRASES},
        primary_exams=["cce"],
    ),
    _issuer(
        "RPSC",
        "Rajasthan Public Service Commission",
        name_hi=["राजस्थान लोक सेवा आयोग"],
        state="Rajasthan",
        state_hi=["राजस्थान"],
        url_hosts=["rpsc.rajasthan.gov.in"],
        aliases=["rpsc"],
        exam_aliases={
            "ras": ["ras", "ras rts", "ras/rts", "rajasthan administrative service", "rts"],
        },
        primary_exams=["ras"],
    ),
    _issuer(
        "HPSC",
        "Haryana Public Service Commission",
        name_hi=["हरियाणा लोक सेवा आयोग"],
        state="Haryana",
        state_hi=["हरियाणा"],
        url_hosts=["hpsc.gov.in"],
        aliases=["hpsc"],
        exam_aliases={"hcs": ["hcs", "haryana civil service"] + _STATE_SERVICE_PHRASES},
        primary_exams=["hcs"],
    ),
    _issuer(
        "PPSC",
        "Punjab Public Service Commission",
        name_hi=["पंजाब लोक सेवा आयोग"],
        state="Punjab",
        state_hi=["पंजाब"],
        url_hosts=["ppsc.gov.in"],
        aliases=["ppsc"],
        exam_aliases={"pcs": ["pcs", "punjab pcs"] + _STATE_SERVICE_PHRASES},
        primary_exams=["pcs"],
    ),
    _issuer(
        "GPSC",
        "Gujarat Public Service Commission",
        name_hi=["गुजरात लोक सेवा आयोग"],
        state="Gujarat",
        state_hi=["गुजरात"],
        url_hosts=["gpsc.gujarat.gov.in"],
        aliases=["gpsc"],
        exam_aliases={"class1": ["class 1", "class i", "gujarat class 1"] + _STATE_SERVICE_PHRASES},
        primary_exams=["class1"],
    ),
    _issuer(
        "MPSC",
        "Maharashtra Public Service Commission",
        name_hi=["महाराष्ट्र लोक सेवा आयोग"],
        state="Maharashtra",
        state_hi=["महाराष्ट्र"],
        url_hosts=["mpsc.gov.in"],
        aliases=["mpsc", "maharashtra psc"],
        exam_aliases={
            "rajyaseva": ["rajyaseva", "rajya seva", "राज्यसेवा", "राज्य सेवा"] + _STATE_SERVICE_PHRASES,
        },
        primary_exams=["rajyaseva"],
    ),
    _issuer(
        "APSC",
        "Assam Public Service Commission",
        name_hi=["असम लोक सेवा आयोग"],
        state="Assam",
        state_hi=["असम"],
        url_hosts=["apsc.nic.in"],
        aliases=["apsc"],
        exam_aliases={"cce": ["cce", "combined competitive examination"] + _STATE_SERVICE_PHRASES},
        primary_exams=["cce"],
    ),
    _issuer(
        "OPSC",
        "Odisha Public Service Commission",
        name_hi=["ओडिशा लोक सेवा आयोग", "ओडिशा लोक सेवा आयोग"],
        state="Odisha",
        state_hi=["ओडिशा", "उड़ीसा"],
        url_hosts=["opsc.gov.in"],
        aliases=["opsc"],
        exam_aliases={"oas": ["oas", "odisha administrative service"] + _STATE_SERVICE_PHRASES},
        primary_exams=["oas"],
    ),
    _issuer(
        "WBPSC",
        "West Bengal Public Service Commission",
        name_hi=["पश्चिम बंगाल लोक सेवा आयोग"],
        state="West Bengal",
        state_hi=["पश्चिम बंगाल"],
        url_hosts=["pscwbapplication.in", "psc.wb.gov.in"],
        aliases=["wbpsc"],
        exam_aliases={"wbcs": ["wbcs", "west bengal civil service", "wbcs exe"]},
        primary_exams=["wbcs"],
    ),
    _issuer(
        "TNPSC",
        "Tamil Nadu Public Service Commission",
        name_hi=["तमिलनाडु लोक सेवा आयोग"],
        state="Tamil Nadu",
        state_hi=["तमिलनाडु", "तमिल नाडु"],
        url_hosts=["tnpsc.gov.in"],
        aliases=["tnpsc"],
        exam_aliases={
            "group1": ["group 1", "group-1", "group i", "tnpsc group 1"],
            "group2": ["group 2", "group-2", "group ii", "tnpsc group 2"],
            "group4": ["group 4", "group-4", "group iv", "tnpsc group 4"],
        },
        primary_exams=["group1"],
    ),
    _issuer(
        "APPSC",
        "Andhra Pradesh Public Service Commission",
        name_hi=["आंध्र प्रदेश लोक सेवा आयोग"],
        state="Andhra Pradesh",
        state_hi=["आंध्र प्रदेश", "आन्ध्र प्रदेश"],
        url_hosts=["psc.ap.gov.in"],
        aliases=["appsc"],
        exam_aliases={"group1": ["group 1", "group-1", "group i"] + _STATE_SERVICE_PHRASES},
        primary_exams=["group1"],
    ),
    _issuer(
        "TSPSC",
        "Telangana State Public Service Commission",
        name_hi=["तेलंगाना राज्य लोक सेवा आयोग"],
        state="Telangana",
        state_hi=["तेलंगाना"],
        url_hosts=["tspsc.gov.in"],
        aliases=["tspsc"],
        exam_aliases={"group1": ["group 1", "group-1", "group i"] + _STATE_SERVICE_PHRASES},
        primary_exams=["group1"],
    ),
    _issuer(
        "KPSC",
        "Karnataka Public Service Commission",
        name_hi=["कर्नाटक लोक सेवा आयोग"],
        state="Karnataka",
        state_hi=["कर्नाटक"],
        url_hosts=["kpsc.kar.nic.in"],
        aliases=["kpsc"],
        exam_aliases={"kas": ["kas", "karnataka administrative service"] + _STATE_SERVICE_PHRASES},
        primary_exams=["kas"],
    ),
    _issuer(
        "KERPSC",
        "Kerala Public Service Commission",
        name_hi=["केरल लोक सेवा आयोग"],
        state="Kerala",
        state_hi=["केरल"],
        url_hosts=["keralapsc.gov.in"],
        aliases=["kerala psc", "keralapsc", "kpsc kerala"],
        exam_aliases={},
        primary_exams=[],
    ),
    _issuer(
        "HPPSC",
        "Himachal Pradesh Public Service Commission",
        name_hi=["हिमाचल प्रदेश लोक सेवा आयोग"],
        state="Himachal Pradesh",
        state_hi=["हिमाचल प्रदेश"],
        url_hosts=["hppsc.hp.gov.in"],
        aliases=["hppsc", "hpcs"],
        exam_aliases={"hpcs": ["hpcs", "himachal administrative service"] + _STATE_SERVICE_PHRASES},
        primary_exams=["hpcs"],
    ),
    _issuer(
        "JKPSC",
        "Jammu and Kashmir Public Service Commission",
        name_hi=["जम्मू और कश्मीर लोक सेवा आयोग", "जम्मू कश्मीर लोक सेवा आयोग"],
        state="Jammu and Kashmir",
        state_hi=["जम्मू और कश्मीर", "जम्मू कश्मीर"],
        url_hosts=["jkpsc.nic.in"],
        aliases=["jkpsc"],
        exam_aliases={"cce": ["cce", "combined competitive examination"] + _STATE_SERVICE_PHRASES},
        primary_exams=["cce"],
    ),
    _issuer(
        "GOAPSC",
        "Goa Public Service Commission",
        name_hi=["गोवा लोक सेवा आयोग"],
        state="Goa",
        state_hi=["गोवा"],
        url_hosts=["gpsc.goa.gov.in"],
        aliases=["goa psc"],
        exam_aliases={},
        primary_exams=[],
    ),
    # ----- Smaller NE PSCs -----
    _issuer(
        "MNPSC",
        "Manipur Public Service Commission",
        name_hi=["मणिपुर लोक सेवा आयोग"],
        state="Manipur",
        state_hi=["मणिपुर"],
        url_hosts=["mpscmanipur.gov.in"],
        aliases=["manipur psc", "mpsc manipur"],
        exam_aliases={"cce": ["cce"] + _STATE_SERVICE_PHRASES},
        primary_exams=["cce"],
    ),
    _issuer(
        "NPSC",
        "Nagaland Public Service Commission",
        name_hi=["नागालैंड लोक सेवा आयोग"],
        state="Nagaland",
        state_hi=["नागालैंड", "नागालैण्ड"],
        url_hosts=["npsc.nagaland.gov.in"],
        aliases=["npsc", "nagaland psc"],
        exam_aliases={},
        primary_exams=[],
    ),
    _issuer(
        "MEGPSC",
        "Meghalaya Public Service Commission",
        name_hi=["मेघालय लोक सेवा आयोग"],
        state="Meghalaya",
        state_hi=["मेघालय"],
        url_hosts=["mpsc.nic.in"],
        aliases=["meghalaya psc", "mpsc meghalaya"],
        exam_aliases={},
        primary_exams=[],
    ),
    _issuer(
        "TPSC",
        "Tripura Public Service Commission",
        name_hi=["त्रिपुरा लोक सेवा आयोग"],
        state="Tripura",
        state_hi=["त्रिपुरा"],
        url_hosts=["tpsc.tripura.gov.in"],
        aliases=["tpsc", "tripura psc"],
        exam_aliases={},
        primary_exams=[],
    ),
    _issuer(
        "APPSCAR",
        "Arunachal Pradesh Public Service Commission",
        name_hi=["अरुणाचल प्रदेश लोक सेवा आयोग"],
        state="Arunachal Pradesh",
        state_hi=["अरुणाचल प्रदेश"],
        url_hosts=["appsc.gov.in"],
        aliases=["arunachal psc", "appsc arunachal"],
        exam_aliases={},
        primary_exams=[],
    ),
    _issuer(
        "SPSC",
        "Sikkim Public Service Commission",
        name_hi=["सिक्किम लोक सेवा आयोग"],
        state="Sikkim",
        state_hi=["सिक्किम"],
        url_hosts=["spscskm.gov.in"],
        aliases=["spsc", "sikkim psc"],
        exam_aliases={},
        primary_exams=[],
    ),
    _issuer(
        "MZPSC",
        "Mizoram Public Service Commission",
        name_hi=["मिजोरम लोक सेवा आयोग"],
        state="Mizoram",
        state_hi=["मिजोरम"],
        url_hosts=["mpsc.mizoram.gov.in"],
        aliases=["mizoram psc", "mpsc mizoram"],
        exam_aliases={},
        primary_exams=[],
    ),
    # ----- High Courts (generic + a few common names) -----
    _issuer(
        "HIGHCOURT",
        "High Court",
        name_hi=["उच्च न्यायालय"],
        aliases=[
            "high court",
            "highcourt",
            "delhi high court",
            "allahabad high court",
            "bombay high court",
            "calcutta high court",
            "madras high court",
            "patna high court",
            "rajasthan high court",
            "madhya pradesh high court",
            "chhattisgarh high court",
            "karnataka high court",
            "kerala high court",
            "gujarat high court",
            "punjab and haryana high court",
        ],
        exam_aliases={},
        primary_exams=[],
        national=True,
    ),
]


def _merge_mcp_registry():
    """Pull url_hosts / names from pathwise-mcp/commission_registry.json if present."""
    candidates = [
        Path(__file__).resolve().parent.parent / "pathwise-mcp" / "commission_registry.json",
        Path(__file__).resolve().parent / "commission_registry.json",
    ]
    data = None
    for p in candidates:
        if p.is_file():
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                break
            except Exception:
                continue
    if not isinstance(data, list):
        return
    by_code = {iss["code"]: iss for iss in ISSUERS}
    for row in data:
        code = (row or {}).get("code")
        if not code:
            continue
        hosts = list(row.get("url_hosts") or [])
        if code in by_code:
            existing = by_code[code]["url_hosts"]
            for h in hosts:
                if h and h not in existing:
                    existing.append(h)
            continue
        ISSUERS.append(_issuer(
            code,
            row.get("name_en") or code,
            name_hi=[row["name_hi"]] if row.get("name_hi") else [],
            state=row.get("state"),
            url_hosts=hosts,
            aliases=list(row.get("search_aliases") or []),
            exam_aliases={},
            national=not row.get("state"),
        ))


_merge_mcp_registry()

# Soft broadeners: never the only search term (they would dump the whole table).
SOFT_TERMS = frozenset({
    "sarkari", "naukri", "sarkarinaukri",
    "government", "govt", "job", "jobs",
    "vacancy", "vacancies", "notification", "notifications",
    "exam", "examination", "recruitment", "bharti",
    "सरकारी", "नौकरी", "वैकेंसी", "भर्ती", "विज्ञप्ति",
    "psc", "commission", "आयोग",
    "sarkari naukri", "government job", "government jobs", "govt job", "govt jobs",
})

_NOISE = frozenset({
    "the", "a", "an", "of", "for", "in", "on", "to", "and", "or", "about",
    "ke", "ki", "ka", "ko", "mein", "me", "se", "hai", "hain",
    "batao", "bata", "bataye", "bare", "baare", "dikhao", "dikhaiye",
    "please", "kya", "karke", "wala", "wali",
    "की", "के", "का", "को", "में", "से", "है", "हैं", "और",
    "बताओ", "बताइए", "बताइये", "बारे", "दिखाओ", "क्या",
})

_LATIN_TOKEN_RE = re.compile(r"[a-z0-9]+(?:\.[a-z0-9]+)+|[a-z0-9]+", re.I)
_DEVANAGARI_RE = re.compile(r"[\u0900-\u097F]+")
_PUNCT_RE = re.compile(r"[!?,;:'\"()\[\]{}|/\\]+")
_SPACE_RE = re.compile(r"\s+")

# Phrase match records: (phrase_lower, kind, issuer_or_none, exam_key_or_none, priority)
# priority: 0=code/alias, 1=host, 2=bound exam, 3=name, 4=state, 5=generic exam
_PHRASES: list = []
_ISSUERS_BY_CODE: dict = {}


def _register_phrase(phrase, kind, issuer, exam_key, priority):
    phrase = (phrase or "").strip().lower()
    if not phrase or phrase in SOFT_TERMS or phrase in _NOISE:
        return
    _PHRASES.append((phrase, kind, issuer, exam_key, priority))


# Phrases shared across many PSCs — never use them to pick one state issuer.
_SHARED_EXAM_PHRASES = set()
for _brand, _phrases in GENERIC_EXAMS.items():
    _SHARED_EXAM_PHRASES.add(_brand.lower())
    _SHARED_EXAM_PHRASES.update(p.lower() for p in _phrases)


def _build_indexes():
    _PHRASES.clear()
    _ISSUERS_BY_CODE.clear()
    for iss in ISSUERS:
        _ISSUERS_BY_CODE[iss["code"]] = iss
        _register_phrase(iss["code"], "code", iss, None, 0)
        for alias in iss["aliases"]:
            _register_phrase(alias, "alias", iss, None, 0)
        _register_phrase(iss["name_en"], "name", iss, None, 3)
        for hi in iss["name_hi"]:
            _register_phrase(hi, "name_hi", iss, None, 3)
        if iss["state"]:
            _register_phrase(iss["state"], "state", iss, None, 4)
        for sh in iss["state_hi"]:
            _register_phrase(sh, "state", iss, None, 4)
        for host in iss["url_hosts"]:
            _register_phrase(host, "host", iss, None, 1)
        for exam_key, phrases in iss["exam_aliases"].items():
            key_phrase = exam_key.replace("_", " ")
            if key_phrase.lower() not in _SHARED_EXAM_PHRASES:
                _register_phrase(key_phrase, "exam", iss, exam_key, 2)
            for p in phrases:
                if p.lower() in _SHARED_EXAM_PHRASES:
                    continue
                _register_phrase(p, "exam", iss, exam_key, 2)
    for brand, phrases in GENERIC_EXAMS.items():
        _register_phrase(brand, "generic_exam", None, brand, 5)
        for p in phrases:
            _register_phrase(p, "generic_exam", None, brand, 5)
    # Longest phrase first so "state service examination" wins over "state service".
    _PHRASES.sort(key=lambda rec: len(rec[0]), reverse=True)


_build_indexes()


def _normalize(raw):
    text = (raw or "").strip()
    text = _PUNCT_RE.sub(" ", text)
    text = text.replace("—", " ").replace("–", " ").replace("‐", " ")
    text = _SPACE_RE.sub(" ", text).strip()
    return text


def _latinize_devanagari(text):
    """Append Latin acronyms for Devanagari exam/commission spellings.

    Match whole Devanagari tokens, longest first, so एमपीपीएससी (MPPSC)
    does not also fire पीपीएससी (PPSC).
    """
    extras = []
    for hi, en in sorted(DEVANAGARI_TO_LATIN.items(), key=lambda kv: len(kv[0]), reverse=True):
        if re.search(r"(?<![\u0900-\u097F])" + re.escape(hi) + r"(?![\u0900-\u097F])", text):
            extras.append(en)
    if not extras:
        return text
    return text + " " + " ".join(extras)


def _phrase_in(text, phrase):
    if not phrase or not text:
        return False
    if " " not in phrase and "." not in phrase and re.match(r"^[a-z0-9]+$", phrase):
        return re.search(r"(?<![a-z0-9])" + re.escape(phrase) + r"(?![a-z0-9])", text) is not None
    return phrase in text


def _filename_form(term):
    return re.sub(r"\s+", "_", term.strip().lower())


def _add_term(terms, seen, value):
    if not value:
        return
    text = str(value).strip()
    if not text:
        return
    key = text.lower()
    if key in seen or key in SOFT_TERMS or key in _NOISE:
        return
    if len(key) < 2:
        return
    seen.add(key)
    terms.append(text)
    if " " in key:
        underscored = _filename_form(key)
        if underscored not in seen:
            seen.add(underscored)
            terms.append(underscored)


def _identity_terms(iss):
    out = [iss["code"], iss["name_en"]]
    out.extend(iss["name_hi"])
    if iss["state"]:
        out.append(iss["state"])
    out.extend(iss["state_hi"])
    out.extend(iss["url_hosts"])
    out.extend(iss["aliases"])
    return out


def _exam_phrases(iss, exam_key):
    phrases = []
    if exam_key:
        phrases.append(exam_key.replace("_", " "))
        phrases.extend(iss["exam_aliases"].get(exam_key, []))
    return phrases


def expand_gov_job_query(raw):
    """Expand a student query into search terms and optional issuer/state/exam.

    Returns:
        {
          "original": str,
          "terms": [str, ...],
          "identity_terms": [str, ...],
          "exam_terms": [str, ...],
          "issuer": str | None,
          "state": str | None,
          "exam_hint": str | None,
          "soft_only": bool,
        }
    """
    original = (raw or "").strip()
    normalized = _normalize(original)
    scan = _latinize_devanagari(normalized).lower() if normalized else ""

    matched = {}  # code -> (priority, issuer, exam_keys set)
    generic_exams = set()
    best_exam = None
    best_exam_priority = 99

    for phrase, kind, iss, exam_key, priority in _PHRASES:
        if not _phrase_in(scan, phrase):
            continue
        # Prefer not to re-hit a short phrase fully inside a longer already-used
        # issuer code ("psc" inside "cgpsc") — word-boundary check already
        # handles latin tokens; this is for multi-word leftovers.
        if kind in ("code", "alias", "host", "name", "name_hi") and iss is not None:
            rec = matched.get(iss["code"])
            if rec is None or priority < rec[0]:
                exams = set(rec[2]) if rec else set()
                if exam_key:
                    exams.add(exam_key)
                matched[iss["code"]] = (priority, iss, exams)
            elif exam_key:
                rec[2].add(exam_key)
        elif kind == "exam" and iss is not None:
            rec = matched.get(iss["code"])
            bound_to = BOUND_EXAMS.get(phrase)
            if rec is None:
                # Only a uniquely bound brand (ras, cse, cgl, …) introduces
                # an issuer. Shared phrases like "state service" must not.
                if bound_to == iss["code"]:
                    matched[iss["code"]] = (
                        min(priority, 2), iss, {exam_key} if exam_key else set()
                    )
                    if exam_key and priority <= best_exam_priority:
                        best_exam = exam_key
                        best_exam_priority = priority
            else:
                if exam_key:
                    rec[2].add(exam_key)
                if exam_key and priority <= best_exam_priority:
                    best_exam = exam_key
                    best_exam_priority = priority
        elif kind == "state" and iss is not None:
            rec = matched.get(iss["code"])
            if rec is None or priority < rec[0]:
                exams = set(rec[2]) if rec else set()
                matched[iss["code"]] = (priority, iss, exams)
        elif kind == "generic_exam":
            if exam_key:
                generic_exams.add(exam_key)
                if best_exam is None or priority <= best_exam_priority:
                    best_exam = exam_key
                    best_exam_priority = priority

    # Bound exam brands (cse, ras, cgl, …) even if phrase loop missed a form.
    tokens = set(_LATIN_TOKEN_RE.findall(scan))
    for tok in tokens:
        bound = BOUND_EXAMS.get(tok)
        if not bound:
            continue
        iss = _ISSUERS_BY_CODE.get(bound)
        if not iss:
            continue
        exam_key = tok
        # Map ias/ips → cse etc. when that phrase sits on the issuer.
        for ek, phrases in iss["exam_aliases"].items():
            bag = {ek.replace("_", " "), *(p.lower() for p in phrases)}
            if tok in bag:
                exam_key = ek
                break
        rec = matched.get(iss["code"])
        if rec is None:
            matched[iss["code"]] = (2, iss, {exam_key})
        else:
            rec[2].add(exam_key)
        if best_exam is None or 2 <= best_exam_priority:
            best_exam = exam_key
            best_exam_priority = 2

    # Police SI / constable only when coupled with a state issuer or "police".
    police_ok = "police" in tokens or "पुलिस" in scan or any(
        rec[1].get("state") for rec in matched.values()
    )
    if not police_ok:
        generic_exams.discard("si")

    terms = []
    identity = []
    exam_terms = []
    seen = set()
    seen_id = set()
    seen_ex = set()
    if original:
        _add_term(terms, seen, original)
        _add_term(terms, seen, normalized)
        _add_term(terms, seen, _filename_form(normalized))

    # Specific exam on a matched issuer: add that exam only, not every exam.
    # Bare issuer: identity + primary exam aliases.
    for _prio, iss, exam_keys in sorted(matched.values(), key=lambda r: r[0]):
        for piece in _identity_terms(iss):
            _add_term(terms, seen, piece)
            _add_term(identity, seen_id, piece)
        keys = set(exam_keys)
        if best_exam:
            keys.add(best_exam)
        if not keys:
            keys.update(iss["primary_exams"])
        # If the user named a specific exam, drop other exams on this issuer
        # (so "upsc cse" does not spray NDA/CDS/ESE).
        if best_exam and best_exam in iss["exam_aliases"]:
            keys = {best_exam}
        elif best_exam and any(best_exam == ek or best_exam in [p.lower() for p in ph]
                               for ek, ph in iss["exam_aliases"].items()):
            keys = {ek for ek, ph in iss["exam_aliases"].items()
                    if best_exam == ek or best_exam in [p.lower() for p in ph]}
        for ek in keys:
            for piece in _exam_phrases(iss, ek):
                _add_term(terms, seen, piece)
                _add_term(exam_terms, seen_ex, piece)

    if not matched:
        for ge in generic_exams:
            for piece in GENERIC_EXAMS.get(ge, [ge]):
                _add_term(terms, seen, piece)
                _add_term(exam_terms, seen_ex, piece)

    # Highest-priority issuer (lowest number) for the structured fields.
    issuer_code = None
    state = None
    if matched:
        top = min(matched.values(), key=lambda r: r[0])
        issuer_code = top[1]["code"]
        # Prefer a state from a state-named match; else the top issuer's state.
        state_hits = [r[1]["state"] for r in matched.values() if r[0] == 4 and r[1]["state"]]
        if state_hits:
            state = state_hits[0]
        elif not top[1]["national"]:
            state = top[1]["state"]

    exam_hint = best_exam
    if not exam_hint and generic_exams:
        exam_hint = next(iter(generic_exams))

    # Did the student type anything other than noise/soft terms?
    content_tokens = []
    for tok in _LATIN_TOKEN_RE.findall(scan):
        if tok not in SOFT_TERMS and tok not in _NOISE:
            content_tokens.append(tok)
    for tok in _DEVANAGARI_RE.findall(normalized):
        if tok not in SOFT_TERMS and tok not in _NOISE and tok not in DEVANAGARI_TO_LATIN:
            # Keep Devanagari content words; acronyms are already latinized.
            if tok not in {"की", "के", "का", "को", "में", "से", "है", "हैं", "और"}:
                content_tokens.append(tok)
    soft_only = not matched and not generic_exams and not content_tokens

    if not terms and original:
        _add_term(terms, seen, original)

    return {
        "original": original,
        "terms": terms,
        "identity_terms": identity,
        "exam_terms": exam_terms,
        "issuer": issuer_code,
        "state": state,
        "exam_hint": exam_hint,
        "soft_only": soft_only,
    }


def fallback_terms(expansion):
    """Narrow retry list: just the state name or just the exam phrase.

    Shared phrases (state service / cce) are only retried when the student
    did not name a specific issuer — otherwise "mppsc" would match every SSE.
    """
    out = []
    seen = set()
    if expansion.get("state"):
        _add_term(out, seen, expansion["state"])
    hint = expansion.get("exam_hint")
    if hint:
        _add_term(out, seen, hint)
        if not expansion.get("issuer"):
            for piece in GENERIC_EXAMS.get(hint, []):
                _add_term(out, seen, piece)
        iss = _ISSUERS_BY_CODE.get(expansion.get("issuer") or "")
        if iss:
            for piece in _exam_phrases(iss, hint):
                if piece.lower() in _SHARED_EXAM_PHRASES:
                    continue
                _add_term(out, seen, piece)
    return out


def normalize_for_match(text):
    """Lowercase and turn filename separators into spaces."""
    if not text:
        return ""
    text = str(text).lower()
    text = text.replace("_", " ").replace("-", " ")
    return _SPACE_RE.sub(" ", text)


def sql_terms(expansion):
    """Terms safe to OR in SQL.

    When an issuer is known, only identity + distinctive (non-shared) exam
    brands are used so "mppsc" does not hit every state's State Service PDF.
    Shared phrases such as "state service examination" are used when the
    student asked generically ("pcs", "राज्य सेवा") or as a later fallback.
    """
    if not expansion.get("issuer"):
        return list(expansion.get("terms") or [])
    out = []
    seen = set()
    for t in (expansion.get("original"),):
        _add_term(out, seen, t)
        if t:
            _add_term(out, seen, _filename_form(t))
    for t in expansion.get("identity_terms") or []:
        _add_term(out, seen, t)
    for t in expansion.get("exam_terms") or []:
        if t.lower() in _SHARED_EXAM_PHRASES or _filename_form(t) in {
            _filename_form(s) for s in _SHARED_EXAM_PHRASES
        }:
            continue
        _add_term(out, seen, t)
    return out


def _competing_issuer_markers(except_code):
    markers = []
    for iss in ISSUERS:
        if iss["code"] == except_code:
            continue
        markers.append(iss["code"].lower())
        if iss["state"]:
            markers.append(iss["state"].lower())
        markers.extend(s.lower() for s in iss["state_hi"])
        for alias in iss["aliases"]:
            if len(alias) >= 4:
                markers.append(alias.lower())
        markers.extend(h.lower() for h in iss["url_hosts"])
    return markers


def haystack_matches(haystack, expansion):
    """True if any expanded term appears in a normalized row haystack.

    When the query named an issuer, identity terms always count; shared exam
    phrases only count if the row does not mention a different commission/state.
    """
    blob = normalize_for_match(haystack)
    if not blob:
        return False

    def _any(term_list):
        for term in term_list or []:
            needle = normalize_for_match(term)
            if len(needle) >= 2 and needle in blob:
                return True
        return False

    issuer = expansion.get("issuer")
    if not issuer:
        return _any(expansion.get("terms"))

    if _any(expansion.get("identity_terms")):
        return True
    if _any([expansion.get("original")]):
        # raw string only — not the shared alias spray
        raw = normalize_for_match(expansion.get("original"))
        if raw and len(raw) >= 3 and raw in blob:
            return True
    if any(normalize_for_match(m) and normalize_for_match(m) in blob
           for m in _competing_issuer_markers(issuer)):
        return False
    return _any(expansion.get("exam_terms"))


def row_search_haystack(row, posts=None):
    """Build a searchable blob from a notification row + optional posts."""
    parts = [
        row.get("job_title"),
        row.get("department"),
        row.get("advertisement_number"),
        row.get("official_url"),
        row.get("local_pdf_path"),
        row.get("qualification"),
        row.get("commission"),
        row.get("state"),
        row.get("exam_name"),
        row.get("exam_kind"),
        row.get("search_document"),
    ]
    trans = row.get("translations")
    if trans:
        parts.append(str(trans))
    for p in posts or []:
        parts.append(p.get("post_name"))
        parts.append(p.get("department"))
    return " ".join(str(p) for p in parts if p)
