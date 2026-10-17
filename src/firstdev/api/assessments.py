# Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform.
"""Assessment routes: candidate taking flow, report and the recruiter view.

Candidate-facing responses are strict allowlist models. They never carry the answer key, rubric,
explanation or model answer; the report (which does) is served only after grading.
"""

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from firstdev import auth
from firstdev.api.applications import VERIFY_MESSAGE, recruiter_application
from firstdev.api.postings import current_recruiter
from firstdev.api.profiles import current_profile
from firstdev.assessments import report, take
from firstdev.assessments.generate import create_assessment
from firstdev.db import get_db
from firstdev.demo import quota
from firstdev.matching.profile import is_verified
from firstdev.models import (
    ApplicationStatus,
    Assessment,
    AssessmentKind,
    AssessmentStatus,
    DeveloperProfile,
    JobPosting,
    User,
)
from firstdev.skills import normalize_skills

router = APIRouter()


class StartOut(BaseModel):
    status: AssessmentStatus
    deadline: datetime | None
    total: int


class CurrentOut(BaseModel):
    question_id: str
    index: int
    total: int
    kind: str
    skill: str
    prompt: str
    options: list[str] | None
    seconds_left: int


class DoneOut(BaseModel):
    done: bool
    status: AssessmentStatus


class AnswerIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question_id: str = Field(max_length=36)
    choice_index: int | None = None
    # Length is judged after sanitizing (take.MAX_ANSWER_CHARS); this only bounds the raw body.
    text: str | None = Field(None, max_length=10_000)


class AnswerOut(BaseModel):
    accepted: bool
    next_index: int


class SubmitOut(BaseModel):
    status: AssessmentStatus


def _mine(db: Session, assessment_id: str, user: User) -> Assessment:
    """Candidate only (404 otherwise); an overdue assessment is finalized on any access."""
    a = auth.get_owned(db, Assessment, assessment_id, user)
    take.finalize_if_expired(db, a)
    return a


@router.post("/assessments/{assessment_id}/start", response_model=StartOut)
def start(
    assessment_id: str, user: User = Depends(auth.current_user), db: Session = Depends(get_db)
) -> StartOut:
    a = _mine(db, assessment_id, user)
    take.start(db, a)
    return StartOut(status=a.status, deadline=a.deadline, total=take.total_questions(db, a))


@router.get("/assessments/{assessment_id}/current", response_model=CurrentOut | DoneOut)
def current(
    assessment_id: str, user: User = Depends(auth.current_user), db: Session = Depends(get_db)
) -> CurrentOut | DoneOut:
    a = _mine(db, assessment_id, user)
    if a.status in (AssessmentStatus.generating, AssessmentStatus.ready):
        raise HTTPException(409, f"assessment is {a.status}")
    q = take.current_question(db, a) if a.status == AssessmentStatus.in_progress else None
    if q is None:
        return DoneOut(done=True, status=a.status)
    total = take.total_questions(db, a)
    left = int((a.deadline - datetime.now(UTC)).total_seconds())
    return CurrentOut(
        question_id=q.id, index=q.position, total=total, kind=q.kind, skill=q.skill,
        prompt=q.prompt, options=q.options, seconds_left=max(0, left),
    )  # fmt: skip


@router.post("/assessments/{assessment_id}/answers", response_model=AnswerOut)
def answer(
    assessment_id: str,
    body: AnswerIn,
    user: User = Depends(auth.current_user),
    db: Session = Depends(get_db),
) -> AnswerOut:
    a = _mine(db, assessment_id, user)
    take.record_answer(db, a, body.question_id, choice_index=body.choice_index, text=body.text)
    q = take.current_question(db, a)
    return AnswerOut(accepted=True, next_index=q.position if q else take.total_questions(db, a))


@router.post("/assessments/{assessment_id}/submit", response_model=SubmitOut)
def submit(
    assessment_id: str, user: User = Depends(auth.current_user), db: Session = Depends(get_db)
) -> SubmitOut:
    a = _mine(db, assessment_id, user)
    take.submit(db, a)
    return SubmitOut(status=a.status)


@router.get("/assessments/{assessment_id}/report", response_model=report.DeveloperReport)
def get_report(
    assessment_id: str, user: User = Depends(auth.current_user), db: Session = Depends(get_db)
) -> report.DeveloperReport:
    return report.developer_report(db, _mine(db, assessment_id, user))


@router.get("/applications/{app_id}/assessment", response_model=report.RecruiterView)
def recruiter_assessment(
    app_id: str, user: User = Depends(current_recruiter), db: Session = Depends(get_db)
) -> report.RecruiterView:
    """Recruiter-sent or automatic assessments for the recruiter's own posting; else 404."""
    a = db.scalar(
        select(Assessment)
        .join(JobPosting, JobPosting.id == Assessment.posting_id)
        .where(
            Assessment.application_id == app_id,
            Assessment.kind.in_([AssessmentKind.recruiter, AssessmentKind.auto]),
            JobPosting.recruiter_id == user.id,
        )
    )
    if a is None:
        raise HTTPException(404, "not found")
    return report.recruiter_view(db, a)


# --- triggers: recruiter send, practice, own list ----------------------------------------------

DAILY_RECRUITER_SENDS = 20
DAILY_PRACTICE = 3
PRACTICE_COOLDOWN = timedelta(days=7)


class Queued(BaseModel):
    assessment_id: str
    status: AssessmentStatus


class PracticeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    skills: list[str] = Field(min_length=1, max_length=3)


class MyAssessmentOut(BaseModel):
    id: str
    kind: AssessmentKind
    status: AssessmentStatus
    skills: list[str]
    overall_pct: float | None
    created_at: datetime


def _count_since(db: Session, *where) -> int:
    since = datetime.now(UTC) - timedelta(hours=24)
    return db.scalar(
        select(func.count()).select_from(Assessment).where(*where, Assessment.created_at > since)
    )


@router.post("/applications/{app_id}/assessment", status_code=202, response_model=Queued)
def send_assessment(
    app_id: str, user: User = Depends(current_recruiter), db: Session = Depends(get_db)
) -> Queued:
    app = recruiter_application(db, app_id, user)  # 404 unless on the recruiter's own posting
    if app.status in (ApplicationStatus.withdrawn, ApplicationStatus.rejected):
        raise HTTPException(409, f"application is {app.status}")
    if db.scalar(select(Assessment.id).where(Assessment.application_id == app.id)):
        raise HTTPException(409, "an assessment was already sent for this application")
    quota.check(db, user, "assessment")  # sandbox AI quota
    if _count_since(db, Assessment.created_by == user.id) >= DAILY_RECRUITER_SENDS:
        raise HTTPException(429, "daily assessment limit reached")
    a = create_assessment(
        db,
        profile=db.get(DeveloperProfile, app.profile_id),
        kind=AssessmentKind.recruiter,
        posting=db.get(JobPosting, app.job_posting_id),
        application=app,
        created_by=user.id,
    )
    return Queued(assessment_id=a.id, status=a.status)


@router.post("/me/assessments", status_code=202, response_model=Queued)
def start_practice(
    body: PracticeIn,
    user: User = Depends(auth.current_user),
    profile: DeveloperProfile = Depends(current_profile),
    db: Session = Depends(get_db),
) -> Queued:
    # Same gate as apply/matches: otherwise throwaway accounts could spend LLM calls.
    if not is_verified(db, profile):
        raise HTTPException(403, VERIFY_MESSAGE)
    skills = normalize_skills(body.skills)
    if not skills:
        raise HTTPException(422, "choose 1-3 usable skills")
    if (
        _count_since(
            db, Assessment.profile_id == profile.user_id, Assessment.kind == AssessmentKind.practice
        )
        >= DAILY_PRACTICE
    ):
        raise HTTPException(429, "daily practice limit reached")
    # A skill is "used" by any practice assessment from the last 7 days that did not fail;
    # expired ones count too (the generation cost was spent and the candidate walked away).
    recent = db.scalars(
        select(Assessment.skills).where(
            Assessment.profile_id == profile.user_id,
            Assessment.kind == AssessmentKind.practice,
            Assessment.status != AssessmentStatus.failed,
            Assessment.created_at > datetime.now(UTC) - PRACTICE_COOLDOWN,
        )
    )
    used = {s for ss in recent for s in ss}
    for s in skills:
        if s in used:
            raise HTTPException(409, f"practice for {s!r} was taken in the last 7 days")
    quota.check(db, user, "assessment")  # sandbox AI quota
    a = create_assessment(
        db, profile=profile, kind=AssessmentKind.practice, skills=skills, created_by=user.id
    )
    return Queued(assessment_id=a.id, status=a.status)


@router.get("/me/assessments", response_model=list[MyAssessmentOut])
def my_assessments(
    profile: DeveloperProfile = Depends(current_profile), db: Session = Depends(get_db)
) -> list[Assessment]:
    return list(
        db.scalars(
            select(Assessment)
            .where(Assessment.profile_id == profile.user_id)
            .order_by(Assessment.created_at.desc())
        )
    )
