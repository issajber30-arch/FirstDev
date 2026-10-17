# Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform.
"""Fingerprints that decide when a cached embedding or match score is stale."""

import hashlib
import json
from datetime import UTC, date, datetime

from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from firstdev.models import (
    BadgeSource,
    CvDocument,
    CvParse,
    CvStatus,
    DeveloperProfile,
    JobPosting,
    RepoAnalysis,
    Repository,
    SkillBadge,
    SkillProfile,
    Tier,
)
from firstdev.pipelines.cv_parser import _month_index
from firstdev.skills import DEPENDENCY_SKILLS, normalize_skill


def posting_fingerprint(posting: JobPosting) -> str:
    """sha256 of the fields that influence matching."""
    data = {
        "title": posting.title,
        "description": posting.description,
        "required_skills": posting.required_skills,
        "optional_skills": posting.optional_skills,
        "tier": posting.tier,
    }
    return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def profile_fingerprint(skills: list[dict], tier: str | None) -> str:
    """sha256 of the skill entries and tier; stable across calls for equal input."""
    data = {"skills": skills, "tier": tier}
    return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


# --- skill profile builder ---------------------------------------------------------------------

_LANG_MIN_SHARE, _LANG_MIN_BYTES = 0.05, 10_240
_LANG_FLOOR_BYTES = 2_048  # below this, a "language" is a stray script, not proof of skill
# Repos judged likely tutorials don't prove skills; the CV claim (0.6 credit) still counts.
TUTORIAL_CUTOFF = 0.7
_JUNIOR_BELOW_MONTHS = 24


def _month_total(experience: list[dict], today: date) -> int | None:
    """Sum of experience months (None if no usable dates); bare years span the whole year."""
    total, seen = 0, False
    for e in experience:
        try:
            s = _month_index(str(e["start"]), is_end=False, today=today)
            en = _month_index(str(e["end"]), is_end=True, today=today)
        except (KeyError, TypeError, ValueError):
            continue
        seen = True
        total += max(0, en - s + 1)
    return total if seen else None


def _merge(into: dict[str, dict], skill: str, level: str, years: float | None, source: str | None):
    cur = into.setdefault(skill, {"skill": skill, "level": level, "years": None, "sources": []})
    if level == "repo" or (level == "assessment" and cur["level"] == "cv"):
        cur["level"] = level  # precedence: repo > assessment > cv
    if years is not None:
        cur["years"] = years if cur["years"] is None else max(cur["years"], years)
    if source and source not in cur["sources"]:
        cur["sources"].append(source)


def latest_cv_parse(db: Session, profile_id: str) -> CvParse | None:
    return db.scalars(
        select(CvParse)
        .join(CvDocument, CvDocument.id == CvParse.cv_document_id)
        .where(CvDocument.profile_id == profile_id, CvDocument.status == CvStatus.parsed)
        .order_by(CvDocument.created_at.desc(), CvParse.created_at.desc())
        .limit(1)
    ).first()


def build_skill_profile(
    db: Session, profile: DeveloperProfile, *, now: datetime | None = None
) -> SkillProfile:
    """Merge CV skills (cv), assessment badges (assessment) and repo evidence (repo); upsert."""
    now = now or datetime.now(UTC)
    merged: dict[str, dict] = {}
    cv = latest_cv_parse(db, profile.user_id)
    cv_data = cv.data if cv else {}
    for s in cv_data.get("skills", []):
        if (n := normalize_skill(str(s.get("name", "")))) is not None:
            _merge(merged, n, "cv", s.get("years"), None)

    # Latest analysis per repository.
    repos = db.scalars(select(Repository).where(Repository.profile_id == profile.user_id)).all()
    for repo in repos:
        a = db.scalars(
            select(RepoAnalysis)
            .where(RepoAnalysis.repository_id == repo.id)
            .order_by(RepoAnalysis.created_at.desc(), RepoAnalysis.id.desc())
            .limit(1)
        ).first()
        if a is None or a.tutorial_likelihood >= TUTORIAL_CUTOFF:
            continue
        src = f"{repo.owner}/{repo.name}"
        langs = {k: v for k, v in (a.metrics.get("languages") or {}).items() if v > 0}
        total = sum(langs.values())
        for lang, size in langs.items():
            if size >= _LANG_FLOOR_BYTES and (
                size >= _LANG_MIN_BYTES or size / total >= _LANG_MIN_SHARE
            ):
                if (n := normalize_skill(lang)) is not None:
                    _merge(merged, n, "repo", None, src)
        for dep in a.metrics.get("dependencies", []):
            if (n := DEPENDENCY_SKILLS.get(str(dep).casefold())) is not None:
                _merge(merged, n, "repo", None, src)

    # Unexpired assessment badges; an expiring badge changes the fingerprint, so scores go stale.
    for b in db.scalars(
        select(SkillBadge).where(
            SkillBadge.profile_id == profile.user_id, SkillBadge.source == BadgeSource.assessment
        )
    ):
        if (b.expires_at is None or b.expires_at > now) and (
            n := normalize_skill(b.skill)
        ) is not None:
            _merge(merged, n, "assessment", None, None)

    skills = sorted(merged.values(), key=lambda e: e["skill"])
    tier = profile.experience_tier
    if tier is None:
        months = _month_total(cv_data.get("experience", []), date.today())
        # The column is NOT NULL: with no experience data we assume the platform's entry tier.
        tier = Tier.mid if months is not None and months >= _JUNIOR_BELOW_MONTHS else Tier.junior
    fp = profile_fingerprint(skills, str(tier))

    sp = db.get(SkillProfile, profile.user_id)
    if sp is None:
        sp = SkillProfile(profile_id=profile.user_id, skills=skills, tier=tier, fingerprint=fp)
        db.add(sp)
    else:
        sp.skills, sp.tier, sp.fingerprint = skills, tier, fp
    db.commit()
    return sp


def is_verified(db: Session, profile: DeveloperProfile) -> bool:
    """A parsed CV and at least one analyzed repository."""
    has_cv = exists().where(
        CvDocument.profile_id == profile.user_id, CvDocument.status == CvStatus.parsed
    )
    has_analysis = (
        exists()
        .where(RepoAnalysis.repository_id == Repository.id)
        .where(Repository.profile_id == profile.user_id)
    )
    return bool(db.scalar(select(has_cv & has_analysis)))
