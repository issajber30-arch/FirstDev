# Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform.
from types import SimpleNamespace

from firstdev.matching.score import apply_review, base_score


def post(req, opt=(), tier="junior"):
    return SimpleNamespace(required_skills=list(req), optional_skills=list(opt), tier=tier)


def sk(**levels):
    return [{"skill": k.replace("_", " "), "level": v} for k, v in levels.items()]


def test_golden_repo_and_cv_mix():
    skills = sk(python="repo", fastapi="repo", docker="cv")
    base, comp = base_score(skills, "junior", post(["python", "fastapi"], ["docker"]))
    assert base == 94.0
    assert comp["required_cov"] == 1.0 and comp["optional_cov"] == 0.6 and comp["tier_fit"] == 1.0
    assert comp["optional"] == [{"skill": "docker", "level": "cv", "credit": 0.6}]


def test_golden_cv_ceiling():
    skills = sk(python="cv", fastapi="cv", docker="cv")
    base, _ = base_score(skills, "junior", post(["python", "fastapi"], ["docker"]))
    assert base == 66.0


def test_empty_requirements_and_optional():
    _, comp = base_score([], "junior", post([]))
    assert comp["required_cov"] == 1.0 and comp["optional_cov"] == 0.0


def test_tier_fit():
    assert base_score([], "junior", post([], tier="mid"))[1]["tier_fit"] == 0.5
    assert base_score([], "mid", post([], tier="junior"))[1]["tier_fit"] == 0.75
    assert base_score([], "junior", post([], tier=None))[1]["tier_fit"] == 1.0
    assert base_score([], None, post([], tier="junior"))[1]["tier_fit"] == 0.5


def test_equivalence_gives_candidate_credit():
    skills = sk(**{"postgres_sql": "repo"})
    p = post(["postgresql"])
    assert base_score(skills, "junior", p)[1]["required_cov"] == 0.0
    _, comp = base_score(skills, "junior", p, {"postgresql": "postgres sql"})
    assert comp["required_cov"] == 1.0


def test_apply_review():
    assert apply_review(94.0, 10) == 100
    assert apply_review(5, -10) == 0
    assert apply_review(50, 99) == 60
