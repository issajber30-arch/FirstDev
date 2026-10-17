# Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform.
"""Matching flows: recruiter ranking and candidate cards, recommended jobs, developer feedback."""

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from firstdev import auth
from firstdev.api.applications import VERIFY_MESSAGE
from firstdev.api.postings import current_recruiter, load_open_posting
from firstdev.api.profiles import current_profile
from firstdev.db import get_db
from firstdev.jobs import enqueue
from firstdev.matching import embeddings
from firstdev.matching.profile import build_skill_profile, is_verified, latest_cv_parse
from firstdev.matching.score import base_score
from firstdev.matching.vectors import from_blob, top_k
from firstdev.models import (
    DeveloperProfile,
    Embedding,
    Job,
    JobKind,
    JobPosting,
    JobStatus,
    MatchScore,
    OwnerKind,
    PostingStatus,
    SkillProfile,
    User,
)
from firstdev.pipelines.match_jobs import _repo_highlights, is_stale

router = APIRouter()

DAILY_RANKS = 5
DAILY_MATCHES = 20
MAX_CARDS = 50
RECALL_K, RECOMMEND_TOP = 50, 20


class JobQueued(BaseModel):
    job_id: str


class RepoCard(BaseModel):
    name: str
    complexity: str | None
    summary: str


class CandidateCard(BaseModel):
    """Allowlist of what a recruiter sees. Add a field here only after a privacy review."""

    profile_id: str
    headline: str | None
    tier: str
    verified_skills: list[str]
    cv_skills: list[str]
    repos: list[RepoCard]
    score: int
    reasons: list[str]
    explained: bool
    stale: bool


class RecommendedJob(BaseModel):
    posting_id: str
    title: str
    tier: str | None
    location: str | None
    remote: bool
    score: int
    matched: list[str]
    missing: list[str]


class RecommendedOut(BaseModel):
    jobs: list[RecommendedJob]
    reason: str | None = None


class MyMatchOut(BaseModel):
    """The developer's own view: no recruiter-facing reasons, no adjustment_reason."""

    score: int
    components: dict
    feedback: dict
    explained: bool
    gaps: list[str]


def _daily_count(db: Session, user: User, kind: JobKind) -> int:
    since = datetime.now(UTC) - timedelta(hours=24)
    return db.scalar(
        select(func.count())
        .select_from(Job)
        .where(Job.user_id == user.id, Job.kind == kind, Job.created_at > since)
    )


@router.post("/postings/{posting_id}/rank", status_code=202, response_model=JobQueued)
def rank_posting(
    posting_id: str, user: User = Depends(current_recruiter), db: Session = Depends(get_db)
) -> JobQueued:
    posting = auth.get_owned(db, JobPosting, posting_id, user)
    if posting.status != PostingStatus.open:
        raise HTTPException(404, "not found")
    if _daily_count(db, user, JobKind.rank_posting) >= DAILY_RANKS:
        raise HTTPException(429, "daily ranking limit reached")
    job = enqueue(db, user, JobKind.rank_posting, {"posting_id": posting.id})
    return JobQueued(job_id=job.id)


@router.get("/postings/{posting_id}/candidates", response_model=list[CandidateCard])
def candidates(
    posting_id: str, user: User = Depends(current_recruiter), db: Session = Depends(get_db)
) -> list[CandidateCard]:
    posting = auth.get_owned(db, JobPosting, posting_id, user)
    rows = db.execute(
        select(MatchScore, DeveloperProfile.headline, SkillProfile)
        .join(DeveloperProfile, DeveloperProfile.user_id == MatchScore.profile_id)
        .outerjoin(SkillProfile, SkillProfile.profile_id == MatchScore.profile_id)
        .where(
            MatchScore.posting_id == posting.id,
            DeveloperProfile.open_to_opportunities.is_(True),  # opt-out hides the card at once
        )
        .order_by(MatchScore.score.desc())
        .limit(MAX_CARDS)
    ).all()
    cards = []
    for ms, headline, sp in rows:
        skills = sp.skills if sp else []
        repos = _repo_highlights(db, db.get(DeveloperProfile, ms.profile_id))
        cards.append(
            CandidateCard(
                profile_id=ms.profile_id,
                headline=headline,
                tier=str(sp.tier) if sp else "",
                verified_skills=[s["skill"] for s in skills if s["level"] == "repo"],
                cv_skills=[s["skill"] for s in skills if s["level"] == "cv"],
                repos=[
                    RepoCard(**{k: r[k] for k in ("name", "complexity", "summary")}) for r in repos
                ],
                score=ms.score,
                reasons=ms.reasons,
                explained=ms.explained,
                stale=sp is None or is_stale(ms, posting, sp),
            )
        )
    return cards


@router.get("/me/recommended-jobs", response_model=RecommendedOut)
def recommended_jobs(
    profile: DeveloperProfile = Depends(current_profile), db: Session = Depends(get_db)
) -> RecommendedOut:
    """Inline from stored vectors: no LLM, no writes."""
    model = embeddings.get_embedder().model
    row = db.scalars(
        select(Embedding).where(
            Embedding.owner_kind == OwnerKind.profile,
            Embedding.profile_id == profile.user_id,
            Embedding.model == model,
        )
    ).first()
    sp = db.get(SkillProfile, profile.user_id)
    if row is None or sp is None:
        return RecommendedOut(jobs=[], reason="profile not verified yet")
    # shortcut: IN-list of every open posting id; fine to ~30k open postings (SQLite variable cap).
    open_ids = list(
        db.scalars(select(JobPosting.id).where(JobPosting.status == PostingStatus.open))
    )
    hits = top_k(
        db, query=from_blob(row.vector, row.dim), owner_kind=OwnerKind.posting, model=model,
        candidate_ids=open_ids, k=RECALL_K,
    )  # fmt: skip
    out = []
    for pid, _ in hits:
        p = db.get(JobPosting, pid)
        base, comp = base_score(sp.skills, sp.tier, p)
        detail = comp["required"] + comp["optional"]
        out.append(
            RecommendedJob(
                posting_id=p.id, title=p.title, tier=str(p.tier) if p.tier else None,
                location=p.location, remote=p.remote, score=round(base),
                matched=[d["skill"] for d in detail if d["level"]],
                missing=[d["skill"] for d in detail if not d["level"]],
            )
        )  # fmt: skip
    out.sort(key=lambda j: j.score, reverse=True)
    return RecommendedOut(jobs=out[:RECOMMEND_TOP])


def _gap_notes(db: Session, profile_id: str) -> list[str]:
    """The developer's own CV gaps, phrased in code. Only ever returned to that developer."""
    cv = latest_cv_parse(db, profile_id)
    return [
        f"{int(g['months'])} months without a listed job between {g['start']} and {g['end']}"
        for g in (cv.data.get("gaps", []) if cv else [])
    ]


@router.get("/me/matches/{posting_id}", response_model=MyMatchOut | JobQueued)
def my_match(
    posting_id: str,
    response: Response,
    user: User = Depends(auth.current_user),
    profile: DeveloperProfile = Depends(current_profile),
    db: Session = Depends(get_db),
) -> MyMatchOut | JobQueued:
    posting = load_open_posting(db, posting_id)
    # Same gate as applying: otherwise throwaway accounts could spend LLM calls.
    if not is_verified(db, profile):
        raise HTTPException(403, VERIFY_MESSAGE)
    sp = build_skill_profile(db, profile)
    ms = db.scalars(
        select(MatchScore).where(
            MatchScore.posting_id == posting.id, MatchScore.profile_id == profile.user_id
        )
    ).first()
    if ms is not None and ms.explained and not is_stale(ms, posting, sp):
        return MyMatchOut(
            score=ms.score,
            components={k: v for k, v in ms.components.items() if k != "adjustment_reason"},
            feedback=ms.feedback,
            explained=True,
            gaps=_gap_notes(db, profile.user_id),
        )
    # Polling while a score is computing must not queue duplicates (each one is an LLM call).
    in_flight = db.scalar(
        select(Job.id).where(
            Job.user_id == user.id,
            Job.kind == JobKind.score_pair,
            Job.status.in_([JobStatus.queued, JobStatus.running]),
            Job.payload["posting_id"].as_string() == posting.id,
        )
    )
    if in_flight is not None:
        response.status_code = 202
        return JobQueued(job_id=in_flight)
    # Only on-demand requests count; scores triggered by applying have their own limit.
    since = datetime.now(UTC) - timedelta(hours=24)
    on_demand = db.scalar(
        select(func.count())
        .select_from(Job)
        .where(
            Job.user_id == user.id,
            Job.kind == JobKind.score_pair,
            Job.created_at > since,
            Job.payload["on_demand"].as_boolean().is_(True),
        )
    )
    if on_demand >= DAILY_MATCHES:
        raise HTTPException(429, "daily match limit reached")
    job = enqueue(
        db,
        user,
        JobKind.score_pair,
        {
            "posting_id": posting.id,
            "profile_id": profile.user_id,
            "explain": True,
            "on_demand": True,
        },
    )
    response.status_code = 202
    return JobQueued(job_id=job.id)
