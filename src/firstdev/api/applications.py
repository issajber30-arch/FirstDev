# Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform.
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from firstdev import auth
from firstdev.api.postings import current_recruiter, load_open_posting
from firstdev.api.profiles import current_profile
from firstdev.assessments.generate import create_assessment
from firstdev.db import get_db
from firstdev.demo import quota
from firstdev.jobs import enqueue
from firstdev.matching.profile import is_verified
from firstdev.models import (
    Application,
    ApplicationStatus,
    ApplicationStatusEvent,
    AssessmentKind,
    DeveloperProfile,
    Invitation,
    InvitationStatus,
    JobKind,
    JobPosting,
    MatchScore,
    User,
)
from firstdev.worlds import same_world

router = APIRouter()

DAILY_APPLICATIONS = 10
VERIFY_MESSAGE = "verify your profile first: a parsed CV and an analyzed repository are required"

S = ApplicationStatus
ALLOWED_TRANSITIONS: dict[ApplicationStatus, set[ApplicationStatus]] = {
    S.submitted: {S.reviewing, S.rejected},
    S.reviewing: {S.interview, S.rejected},
    S.interview: {S.accepted, S.rejected},
}
WITHDRAWABLE = {S.submitted, S.reviewing, S.interview}


class StatusIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: ApplicationStatus


class Queued(BaseModel):
    application_id: str
    status: ApplicationStatus
    job_id: str
    assessment_id: str | None = None  # set when the posting has auto_assessment on


class StatusOut(BaseModel):
    application_id: str
    status: ApplicationStatus


class MyApplicationOut(BaseModel):
    application_id: str
    posting_id: str
    title: str
    status: ApplicationStatus
    created_at: datetime
    score: int | None
    feedback: dict | None  # the applicant's own feedback; never shown to recruiters


class RecruiterApplicationOut(BaseModel):
    """Allowlist of what a recruiter sees: no CV text, contact, education or feedback."""

    application_id: str
    profile_id: str
    headline: str | None
    status: ApplicationStatus
    created_at: datetime
    score: int | None
    components: dict | None
    reasons: list | None
    injection_flags: list


def _log(db: Session, app: Application, to: ApplicationStatus, actor: User) -> None:
    db.add(
        ApplicationStatusEvent(
            application_id=app.id, from_status=app.status, to_status=to, actor_id=actor.id
        )
    )
    app.status = to


def recruiter_application(db: Session, app_id: str, user: User) -> Application:
    """The application if it belongs to one of the recruiter's postings, else 404."""
    app = db.scalar(
        same_world(  # defence in depth: the applicant must live in the recruiter's world
            select(Application)
            .join(JobPosting, JobPosting.id == Application.job_posting_id)
            .where(Application.id == app_id, JobPosting.recruiter_id == user.id),
            Application.profile_id,
            user,
        )
    )
    if app is None:
        raise HTTPException(404, "not found")
    return app


@router.post("/postings/{posting_id}/apply", status_code=201, response_model=Queued)
def apply(
    posting_id: str,
    user: User = Depends(auth.current_user),
    profile: DeveloperProfile = Depends(current_profile),
    db: Session = Depends(get_db),
) -> Queued:
    posting = load_open_posting(db, posting_id, user)
    if not is_verified(db, profile):
        raise HTTPException(403, VERIFY_MESSAGE)
    quota.check(db, user, "score_pair")  # applying queues an explaining score
    since = datetime.now(UTC) - timedelta(hours=24)
    recent = db.scalar(
        select(func.count())
        .select_from(Application)
        .where(Application.profile_id == profile.user_id, Application.created_at > since)
    )
    if recent >= DAILY_APPLICATIONS:
        raise HTTPException(429, "daily application limit reached")
    app = Application(job_posting_id=posting.id, profile_id=profile.user_id)
    db.add(app)
    try:
        db.flush()
    except IntegrityError:  # unique (posting, profile)
        db.rollback()
        raise HTTPException(409, "already applied") from None
    db.add(
        ApplicationStatusEvent(
            application_id=app.id, from_status=None, to_status=S.submitted, actor_id=user.id
        )
    )
    invite = db.scalar(
        select(Invitation).where(
            Invitation.posting_id == posting.id,
            Invitation.profile_id == profile.user_id,
            Invitation.status == InvitationStatus.sent,
        )
    )
    if invite is not None:
        invite.status = InvitationStatus.accepted
    db.flush()
    assessment = None
    if posting.auto_assessment:  # queues its own generation job; commits the application too
        assessment = create_assessment(
            db, profile=profile, kind=AssessmentKind.auto, posting=posting, application=app,
            created_by=None,
        )  # fmt: skip
    # Ids only: no CV or posting text in the jobs table. enqueue() commits everything.
    job = enqueue(
        db,
        user,
        JobKind.score_pair,
        {
            "posting_id": posting.id,
            "profile_id": profile.user_id,
            "explain": True,
            "application_id": app.id,
        },
    )
    return Queued(
        application_id=app.id,
        status=app.status,
        job_id=job.id,
        assessment_id=assessment.id if assessment else None,
    )


@router.post("/applications/{app_id}/withdraw", response_model=StatusOut)
def withdraw(
    app_id: str,
    user: User = Depends(auth.current_user),
    db: Session = Depends(get_db),
) -> StatusOut:
    app = auth.get_owned(db, Application, app_id, user)  # applicant only
    if app.status not in WITHDRAWABLE:
        raise HTTPException(409, f"cannot withdraw from status {app.status}")
    _log(db, app, S.withdrawn, user)
    db.commit()
    return StatusOut(application_id=app.id, status=app.status)


@router.post("/applications/{app_id}/status", response_model=StatusOut)
def change_status(
    app_id: str,
    body: StatusIn,
    user: User = Depends(current_recruiter),
    db: Session = Depends(get_db),
) -> StatusOut:
    app = recruiter_application(db, app_id, user)
    if body.status not in ALLOWED_TRANSITIONS.get(app.status, set()):
        raise HTTPException(409, f"cannot move from {app.status} to {body.status}")
    _log(db, app, body.status, user)
    db.commit()
    return StatusOut(application_id=app.id, status=app.status)


@router.get("/me/applications", response_model=list[MyApplicationOut])
def my_applications(
    user: User = Depends(auth.current_user),
    profile: DeveloperProfile = Depends(current_profile),
    db: Session = Depends(get_db),
) -> list[MyApplicationOut]:
    rows = db.execute(
        same_world(  # defence in depth: the posting's recruiter must share the caller's world
            select(Application, JobPosting.title, MatchScore)
            .join(JobPosting, JobPosting.id == Application.job_posting_id)
            .outerjoin(MatchScore, MatchScore.id == Application.match_score_id)
            .where(Application.profile_id == profile.user_id)
            .order_by(Application.created_at.desc()),
            JobPosting.recruiter_id,
            user,
        )
    )
    return [
        MyApplicationOut(
            application_id=a.id,
            posting_id=a.job_posting_id,
            title=title,
            status=a.status,
            created_at=a.created_at,
            score=m.score if m else None,
            feedback=m.feedback if m else None,
        )
        for a, title, m in rows
    ]


@router.get("/postings/{posting_id}/applications", response_model=list[RecruiterApplicationOut])
def posting_applications(
    posting_id: str, user: User = Depends(current_recruiter), db: Session = Depends(get_db)
) -> list[RecruiterApplicationOut]:
    posting = auth.get_owned(db, JobPosting, posting_id, user)
    rows = db.execute(
        same_world(  # applicants from another world never appear
            select(Application, DeveloperProfile.headline, MatchScore)
            .join(DeveloperProfile, DeveloperProfile.user_id == Application.profile_id)
            .outerjoin(MatchScore, MatchScore.id == Application.match_score_id)
            .where(Application.job_posting_id == posting.id)
            .order_by(Application.created_at.desc()),
            Application.profile_id,
            user,
        )
    )
    return [
        RecruiterApplicationOut(
            application_id=a.id,
            profile_id=a.profile_id,
            headline=headline,
            status=a.status,
            created_at=a.created_at,
            score=m.score if m else None,
            components=m.components if m else None,
            reasons=m.reasons if m else None,
            injection_flags=posting.injection_flags,
        )
        for a, headline, m in rows
    ]
