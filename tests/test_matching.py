from matching import (
    education_compatible, scholarship_match_explanation, scholarship_matches_profile,
    score_riasec, stream_fits_cluster, parse_flexible_date, is_national_job,
)


def test_education_class_overlap():
    ok, _ = education_compatible("Class 11-12", "Class 9-12")
    assert ok
    ok, _ = education_compatible("Class 9-10", "UG")
    assert not ok
    ok, _ = education_compatible("Undergraduate", "UG")
    assert ok


def test_scholarship_income_and_category():
    sch = {
        "education_level": "UG",
        "states": "All",
        "categories": "OBC",
        "gender": "All",
        "income_ceiling": 250000,
        "requires_disability": False,
    }
    profile = {
        "education_level": "Undergraduate",
        "state": "Maharashtra",
        "category": "OBC",
        "gender": "Female",
        "income_bracket": 200000,
        "has_disability": False,
        "is_minority": False,
    }
    expl = scholarship_match_explanation(sch, profile)
    assert expl["matched"]
    profile["income_bracket"] = 400000
    assert not scholarship_matches_profile(sch, profile)


def test_disability_scholarship():
    sch = {
        "education_level": "UG",
        "states": "All",
        "categories": "All",
        "gender": "All",
        "income_ceiling": None,
        "requires_disability": True,
    }
    profile = {
        "education_level": "Undergraduate",
        "state": "Delhi",
        "category": "General",
        "gender": "Male",
        "income_bracket": None,
        "has_disability": False,
    }
    assert not scholarship_matches_profile(sch, profile)
    profile["has_disability"] = True
    assert scholarship_matches_profile(sch, profile)


def test_stream_clusters():
    assert stream_fits_cluster("pcb", "healthcare")
    assert not stream_fits_cluster("pcb", "tech")
    assert stream_fits_cluster("undecided", "tech")


def test_riasec_scoring():
    answers = {"I1": "yes", "I2": "yes", "S1": "yes", "R1": "no"}
    top, tallies = score_riasec(answers)
    assert tallies["I"] == 2
    assert top[0] == "I"


def test_parse_dates_and_national_job():
    assert parse_flexible_date("2026-10-31").year == 2026
    assert is_national_job({"commission": "UPSC", "state": "Delhi"})
    assert not is_national_job({"commission": "CGPSC", "state": "Chhattisgarh", "exam_name": "State Service"})
