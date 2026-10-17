# Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform.
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from firstdev import auth
from firstdev.api.profiles import current_profile
from firstdev.db import get_db
from firstdev.github import InvalidRepoUrl, parse_repo_url
from firstdev.jobs import enqueue
from firstdev.models import (
    DeveloperProfile,
    Job,
    JobKind,
    JobStatus,
    RepoAnalysis,
    Repository,
    User,
)

router = APIRouter()

DAILY_QUOTA = 20
MAX_REPOS = 50


class RepoIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: str = Field(max_length=300)


class RepoQueued(BaseModel):
    repo_id: str
    job_id: str
    status: JobStatus


class RepoOut(BaseModel):
    id: str
    owner: str
    name: str
    is_fork: bool
    stars: int


class AnalysisOut(BaseModel):
    commit_sha: str
    metrics: dict
    assessment: dict
    tutorial_likelihood: float
    model: str
    created_at: datetime


class RepoAnalysisOut(BaseModel):
    repo: RepoOut
    status: JobStatus | None
    last_error: str | None
    analysis: AnalysisOut | None


def _latest_job(db: Session, user: User, repo_id: str, *statuses: JobStatus) -> Job | None:
    q = select(Job).where(
        Job.user_id == user.id,
        Job.kind == JobKind.repo_analyze,
        Job.payload["repository_id"].as_string() == repo_id,
    )
    if statuses:
        q = q.where(Job.status.in_(statuses))
    return db.scalar(q.order_by(Job.created_at.desc()).limit(1))


@router.post("/profiles/me/repos", status_code=202, response_model=RepoQueued)
def add_repo(
    body: RepoIn,
    response: Response,
    user: User = Depends(auth.current_user),
    profile: DeveloperProfile = Depends(current_profile),
    db: Session = Depends(get_db),
) -> RepoQueued:
    try:
        owner, name = parse_repo_url(body.url)
    except InvalidRepoUrl:
        raise HTTPException(422, "not a valid GitHub repository URL") from None
    owner, name = owner.lower(), name.lower()  # GitHub names are case-insensitive

    repo = db.scalar(
        select(Repository).where(
            Repository.profile_id == profile.user_id,
            Repository.owner == owner,
            Repository.name == name,
        )
    )
    if repo is not None:
        running = _latest_job(db, user, repo.id, JobStatus.queued, JobStatus.running)
        if running is not None:
            response.status_code = 200
            return RepoQueued(repo_id=repo.id, job_id=running.id, status=running.status)

    since = datetime.now(UTC) - timedelta(hours=24)
    recent = db.scalar(
        select(func.count())
        .select_from(Job)
        .where(Job.user_id == user.id, Job.kind == JobKind.repo_analyze, Job.created_at > since)
    )
    if recent >= DAILY_QUOTA:
        raise HTTPException(429, "daily repository analysis limit reached")

    if repo is None:
        total = db.scalar(
            select(func.count())
            .select_from(Repository)
            .where(Repository.profile_id == profile.user_id)
        )
        if total >= MAX_REPOS:
            raise HTTPException(409, "repository limit reached")
        repo = Repository(profile_id=profile.user_id, owner=owner, name=name)
        db.add(repo)
        db.flush()
    # Payload is only an id; enqueue() commits the repository and the job together.
    job = enqueue(db, user, JobKind.repo_analyze, {"repository_id": repo.id})
    return RepoQueued(repo_id=repo.id, job_id=job.id, status=job.status)


@router.get("/repos/{repo_id}/analysis", response_model=RepoAnalysisOut)
def get_analysis(
    repo_id: str, user: User = Depends(auth.current_user), db: Session = Depends(get_db)
) -> RepoAnalysisOut:
    repo = auth.get_owned(db, Repository, repo_id, user)
    job = _latest_job(db, user, repo.id)
    analysis = db.scalar(
        select(RepoAnalysis)
        .where(RepoAnalysis.repository_id == repo.id)
        .order_by(RepoAnalysis.created_at.desc())
        .limit(1)
    )
    return RepoAnalysisOut(
        repo=RepoOut(
            id=repo.id, owner=repo.owner, name=repo.name, is_fork=repo.is_fork, stars=repo.stars
        ),
        status=job.status if job else None,
        last_error=job.last_error if job else None,
        analysis=AnalysisOut(
            commit_sha=analysis.commit_sha,
            metrics=analysis.metrics,
            assessment=analysis.assessment,
            tutorial_likelihood=analysis.tutorial_likelihood,
            model=analysis.model,
            created_at=analysis.created_at,
        )
        if analysis
        else None,
    )
