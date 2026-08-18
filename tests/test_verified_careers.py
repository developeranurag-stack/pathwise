from verified_careers import NEW_VERIFIED, EXTRA_EXAMS, EXTRA_SCHOLARSHIPS
from content_seed import CORE_CAREER_SLUGS


REQUIRED = {
    "slug", "name", "cluster", "description", "demand", "salary_min", "salary_max",
    "skills", "ai_impact", "education_path", "exams", "riasec", "wlb", "remote",
    "mid", "senior", "related", "institutes", "steps",
}

CLUSTERS = {"tech", "science", "business", "creative", "healthcare", "social", "engineering", "law"}
STAGES = {
    "After Class 10", "After Class 12", "During Graduation", "Skill Development",
    "Internships", "First Job", "Career Growth Milestones",
}


def test_new_verified_unique_and_complete():
    slugs = [c["slug"] for c in NEW_VERIFIED]
    assert len(slugs) == len(set(slugs))
    assert len(slugs) >= 35
    for spec in NEW_VERIFIED:
        missing = REQUIRED - spec.keys()
        assert not missing, f"{spec['slug']} missing {missing}"
        assert spec["cluster"] in CLUSTERS
        assert spec["salary_min"] < spec["salary_max"]
        assert spec["mid"][0] < spec["mid"][1]
        for stage, _desc, _order in spec["steps"]:
            assert stage in STAGES, f"{spec['slug']} bad stage {stage}"


def test_related_point_at_known_slugs():
    known = set(CORE_CAREER_SLUGS)
    for spec in NEW_VERIFIED:
        for rel in spec["related"]:
            assert rel in known, f"{spec['slug']} related unknown {rel}"


def test_extra_catalogues():
    assert len(EXTRA_EXAMS) >= 8
    assert len(EXTRA_SCHOLARSHIPS) >= 6
    names = [s["name"] for s in EXTRA_SCHOLARSHIPS]
    assert len(names) == len(set(names))
