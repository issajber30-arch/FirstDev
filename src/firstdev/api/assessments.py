# Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform.
"""Assessment routes: candidate taking flow, report and the recruiter view.

Candidate-facing responses are strict allowlist models. They never carry the answer key, rubric,
explanation or model answer; the report (which does) is served only after grading.
"""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from firstdev import auth
from firstdev.api.postings import current_recruiter
from firstdev.assessments import report, take
from firstdev.db import get_db
from firstdev.models import (
    Assessment,
    AssessmentKind,
    AssessmentStatus,
    JobPosting,
    User,
)

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
