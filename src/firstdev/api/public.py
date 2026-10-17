# Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform.
"""Public developer pages: opt-in, real world only, verified badges only."""

from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from firstdev import auth
from firstdev.api.profiles import normalize_handle
from firstdev.db import get_db
from firstdev.matching.profile import compute_skills
from firstdev.models import (
    BadgeSource,
    DeveloperProfile,
    RepoAnalysis,
    Repository,
    Role,
    SkillBadge,
    User,
)

router = APIRouter()


class PublicBadge(BaseModel):
    skill: str
    source: Literal["repo", "assessment"]
    verified_at: datetime


class PublicProfileOut(BaseModel):
    """Allowlist: never CV-only skills, scores, CV text, contacts or email."""

    handle: str
    display_name: str | None
    headline: str | None
    tier: str | None
    verified_badges: list[PublicBadge]


def _repo_dates(db: Session, profile_id: str) -> dict[str, datetime]:
    """`owner/name` -> created_at of that repository's latest analysis."""
    rows = db.execute(
        select(Repository.owner, Repository.name, RepoAnalysis.created_at)
        .join(RepoAnalysis, RepoAnalysis.repository_id == Repository.id)
        .where(Repository.profile_id == profile_id)
    )
    out: dict[str, datetime] = {}
    for owner, name, at in rows:
        src = f"{owner}/{name}"
        if src not in out or at > out[src]:
            out[src] = at
    return out


def verified_badges(
    db: Session, profile: DeveloperProfile, skills: list[dict], now: datetime
) -> list[PublicBadge]:
    """Skill-profile entries at level repo (dated by the latest analysis of the repos that
    contributed them) plus unexpired assessment badges. CV-only skills never qualify."""
    dates = _repo_dates(db, profile.user_id)
    out = []
    for s in skills:
        if s["level"] != "repo":
            continue
        when = [dates[src] for src in s["sources"] if src in dates]
        if when:
            out.append(PublicBadge(skill=s["skill"], source="repo", verified_at=max(when)))
    for b in db.scalars(
        select(SkillBadge).where(
            SkillBadge.profile_id == profile.user_id, SkillBadge.source == BadgeSource.assessment
        )
    ):
        if b.expires_at is None or b.expires_at > now:
            out.append(PublicBadge(skill=b.skill, source="assessment", verified_at=b.created_at))
    return sorted(out, key=lambda b: (b.skill, b.source))


@router.get("/u/{handle}", response_model=PublicProfileOut)
def public_profile(
    handle: str, request: Request, response: Response, db: Session = Depends(get_db)
) -> PublicProfileOut:
    # Every request counts (hits and misses), so handles can't be probed for free.
    if not auth.public_profile_limiter.hit(auth.client_ip(request)):
        raise HTTPException(429, "too many requests")
    h = normalize_handle(handle)
    # One answer for invalid, unknown, private, recruiter and sandbox: no way to tell them apart.
    user = (
        db.scalar(
            select(User).where(
                User.handle == h,
                User.public_profile.is_(True),
                User.world_id.is_(None),
                User.role == Role.developer,
            )
        )
        if h
        else None
    )
    profile = db.get(DeveloperProfile, user.id) if user else None
    if user is None or profile is None:
        raise HTTPException(404, "not found")
    now = datetime.now(UTC)
    skills, tier = compute_skills(db, profile, now)
    response.headers["Cache-Control"] = "public, max-age=60"
    return PublicProfileOut(
        handle=user.handle,
        display_name=user.display_name,
        headline=profile.headline,
        tier=str(tier),
        verified_badges=verified_badges(db, profile, skills, now),
    )
