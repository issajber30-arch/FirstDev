# Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform.
from firstdev.matching.profile import build_skill_profile, profile_fingerprint
from firstdev.models import (
    CvDocument,
    CvParse,
    CvStatus,
    RepoAnalysis,
    Repository,
    SkillProfile,
    Tier,
)


def add_cv(db, profile, skills, experience=()):
    doc = CvDocument(profile_id=profile.user_id, sha256="h", size=1, status=CvStatus.parsed)
    db.add(doc)
    db.flush()
    db.add(
        CvParse(
            cv_document_id=doc.id,
            schema_version=1,
            model="m",
            data={
                "skills": [{"name": n, "years": y} for n, y in skills],
                "experience": list(experience),
            },
        )
    )
    db.commit()


def add_repo(db, profile, name, languages=None, deps=(), fork=False, tutorial=0.1):
    repo = Repository(profile_id=profile.user_id, owner="o", name=name, is_fork=fork)
    db.add(repo)
    db.flush()
    db.add(
        RepoAnalysis(
            repository_id=repo.id,
            commit_sha="a" * 40,
            metrics={"languages": languages or {}, "dependencies": list(deps)},
            assessment={},
            tutorial_likelihood=tutorial,
            model="m",
        )
    )
    db.commit()


def by_skill(sp):
    return {e["skill"]: e for e in sp.skills}


def test_cv_only(db, profile):
    add_cv(db, profile, [("JS", 2), ("Python", None)])
    sp = build_skill_profile(db, profile)
    assert [(e["skill"], e["level"]) for e in sp.skills] == [
        ("javascript", "cv"),
        ("python", "cv"),
    ]
    assert by_skill(sp)["javascript"]["years"] == 2


def test_repo_dependency_and_language_thresholds(db, profile):
    add_repo(
        db,
        profile,
        "r",
        languages={"Python": 100_000, "Shell": 100, "HTML": 12_000},
        deps=["fastapi", "unknown-pkg"],
    )
    sk = by_skill(build_skill_profile(db, profile))
    assert sk["fastapi"]["level"] == "repo" and sk["fastapi"]["sources"] == ["o/r"]
    assert sk["python"]["level"] == "repo" and sk["html"]["level"] == "repo"  # >= 10 KB
    assert "shell" not in sk and "unknown-pkg" not in sk


def test_five_percent_rule(db, profile):
    add_repo(db, profile, "r", languages={"Python": 1_000_000, "Go": 6_000, "Lua": 4_000})
    sk = by_skill(build_skill_profile(db, profile))
    assert "go" not in sk and "lua" not in sk  # < 5% and < 10 KB
    add_repo(db, profile, "s", languages={"Rust": 3_000, "C": 2_500})
    sk = by_skill(build_skill_profile(db, profile))
    assert "rust" in sk and "c" in sk  # 60% / 40% of their own repo


def test_repo_beats_cv_and_keeps_years(db, profile):
    add_cv(db, profile, [("FastAPI", 3)])
    add_repo(db, profile, "r", deps=["fastapi"])
    e = by_skill(build_skill_profile(db, profile))["fastapi"]
    assert (e["level"], e["years"], e["sources"]) == ("repo", 3, ["o/r"])


def test_only_latest_analysis_per_repo(db, profile):
    add_repo(db, profile, "r", deps=["django"])
    repo = db.query(Repository).one()
    db.add(
        RepoAnalysis(
            repository_id=repo.id,
            commit_sha="b" * 40,
            metrics={"languages": {}, "dependencies": ["flask"]},
            assessment={},
            tutorial_likelihood=0.1,
            model="m",
        )
    )
    db.commit()
    sk = by_skill(build_skill_profile(db, profile))
    assert "flask" in sk and "django" not in sk


def test_review_focus_3_tiny_languages_add_nothing(db, profile):
    add_cv(db, profile, [("Python", 1), ("SQL", None)])
    # 25 languages at 4% each and 2.5 KB total: every one is under both thresholds.
    add_repo(db, profile, "tut", languages={f"Lang{i}": 100 for i in range(25)}, fork=True)
    sp = build_skill_profile(db, profile)
    assert {(e["skill"], e["level"]) for e in sp.skills} == {("python", "cv"), ("sql", "cv")}


def test_cv_with_repos_without_signal(db, profile):
    add_cv(db, profile, [("Python", 1), ("SQL", None)])
    add_repo(db, profile, "empty")  # no languages, no deps
    sp = build_skill_profile(db, profile)
    assert {(e["skill"], e["level"]) for e in sp.skills} == {("python", "cv"), ("sql", "cv")}


def test_no_data_at_all(db, profile):
    sp = build_skill_profile(db, profile)
    assert sp.skills == [] and sp.tier == Tier.junior


def test_tier_set_derived_and_default(db, profile):
    exp = [{"start": "2020-01", "end": "2022-06"}]
    add_cv(db, profile, [], exp)
    assert build_skill_profile(db, profile).tier == Tier.mid  # 30 months
    profile.experience_tier = Tier.junior
    db.commit()
    assert build_skill_profile(db, profile).tier == Tier.junior  # explicit wins


def test_tier_junior_when_short(db, profile):
    add_cv(db, profile, [], [{"start": "2024-01", "end": "2024-12"}])
    assert build_skill_profile(db, profile).tier == Tier.junior


def test_upsert_keeps_single_row_and_fingerprint_stable(db, profile):
    add_cv(db, profile, [("Python", 1)])
    a = build_skill_profile(db, profile).fingerprint
    assert build_skill_profile(db, profile).fingerprint == a
    assert db.query(SkillProfile).count() == 1
    add_repo(db, profile, "r", deps=["django"])
    assert build_skill_profile(db, profile).fingerprint != a
    assert db.query(SkillProfile).count() == 1


def test_fingerprint_changes_with_skill_or_tier():
    s = [{"skill": "python", "level": "cv", "years": 1, "sources": []}]
    assert profile_fingerprint(s, "mid") == profile_fingerprint(list(s), "mid")
    assert profile_fingerprint(s, "mid") != profile_fingerprint(s, "junior")
    assert profile_fingerprint(s, "mid") != profile_fingerprint([{**s[0], "level": "repo"}], "mid")


def test_stray_script_below_floor_proves_nothing(db, profile):
    # 100% of its repo, but a 300-byte script isn't evidence of the language.
    add_repo(db, profile, "tiny", languages={"Shell": 300})
    assert "shell" not in by_skill(build_skill_profile(db, profile))


def test_tutorial_repo_gives_no_repo_credit(db, profile):
    add_cv(db, profile, [("FastAPI", 2)])
    add_repo(db, profile, "todo-app", languages={"Python": 50_000}, deps=["fastapi"], tutorial=0.9)
    sk = by_skill(build_skill_profile(db, profile))
    assert "python" not in sk  # only proven by the tutorial repo
    assert sk["fastapi"]["level"] == "cv"  # CV claim still counts at cv level
