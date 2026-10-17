# Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform.
import dataclasses
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from firstdev import auth
from firstdev.db import get_db
from firstdev.jobs import enqueue
from firstdev.matching.profile import posting_fingerprint
from firstdev.models import JobKind, JobPosting, PostingStatus, Role, Tier, User
from firstdev.security.injection import scan
from firstdev.security.sanitize import (
    EmptyInput,
    InputTooLarge,
    sanitize_text,
    sanitize_text_report,
)
from firstdev.skills import normalize_skills
from firstdev.worlds import same_world

router = APIRouter(prefix="/postings")

MAX_DESCRIPTION = 10_000
MAX_REQUIRED = 20
MAX_OPTIONAL = 20
# Raw list bound, applied before normalization so a huge list is rejected cheaply.
MAX_RAW_SKILLS = 100

Skill = Annotated[str, StringConstraints(max_length=200)]


class PostingIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=200)
    description: str  # sanitized and length-checked in the handler (413, not 422)
    required_skills: list[Skill] = Field(max_length=MAX_RAW_SKILLS)
    optional_skills: list[Skill] = Field(default_factory=list, max_length=MAX_RAW_SKILLS)
    tier: Tier | None = None
    salary_min: int | None = Field(None, ge=0)
    salary_max: int | None = Field(None, ge=0)
    currency: str | None = Field(None, pattern=r"^[A-Z]{3}$")
    location: str | None = Field(None, min_length=1, max_length=100)
    remote: bool = False
    auto_assessment: bool = False  # apply also creates an assessment (LLM cost: opt-in)
    # Create: omitted means draft. Update: omitted keeps the current status.
    status: Literal["draft", "open"] | None = None

    @model_validator(mode="after")
    def _salary_order(self) -> "PostingIn":
        if None not in (self.salary_min, self.salary_max) and self.salary_min > self.salary_max:
            raise ValueError("salary_min must be <= salary_max")
        return self


class PostingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    description: str
    required_skills: list[str]
    optional_skills: list[str]
    tier: Tier | None
    salary_min: int | None
    salary_max: int | None
    currency: str | None
    location: str | None
    remote: bool
    status: PostingStatus
    created_at: datetime
    injection_flags: list | None  # owner only; None for other viewers
    auto_assessment: bool | None = None  # owner only; None for other viewers


def current_recruiter(user: User = Depends(auth.current_user)) -> User:
    if user.role != Role.recruiter:
        raise HTTPException(404, "not found")
    return user


def load_open_posting(db: Session, posting_id: str, caller: User) -> JobPosting:
    """An open posting from the caller's own world; 404 for anything else."""
    posting = db.scalar(
        same_world(
            select(JobPosting).where(JobPosting.id == posting_id), JobPosting.recruiter_id, caller
        )
    )
    if posting is None or posting.status != PostingStatus.open:
        raise HTTPException(404, "not found")
    return posting


def _out(posting: JobPosting, *, owner: bool) -> PostingOut:
    out = PostingOut.model_validate(posting)
    if not owner:
        out.injection_flags = None
        out.auto_assessment = None
    return out


def _apply(posting: JobPosting, body: PostingIn) -> None:
    """Validate and copy the editable fields onto the row."""
    try:
        description, removed = sanitize_text_report(body.description, MAX_DESCRIPTION)
        title = sanitize_text(body.title, 200)
    except InputTooLarge:
        raise HTTPException(413, "description too large") from None
    except EmptyInput:
        raise HTTPException(422, "title and description must not be empty") from None
    required = normalize_skills(body.required_skills)
    if not 1 <= len(required) <= MAX_REQUIRED:
        raise HTTPException(422, f"required skills: 1-{MAX_REQUIRED} are needed")
    # A skill listed as required is not also optional.
    optional = [s for s in normalize_skills(body.optional_skills) if s not in required]
    if len(optional) > MAX_OPTIONAL:
        raise HTTPException(422, f"optional skills: at most {MAX_OPTIONAL}")
    posting.title = title
    posting.description = description
    posting.injection_flags = [dataclasses.asdict(f) for f in scan(description, removed)]
    posting.required_skills = required
    posting.optional_skills = optional
    for f in (
        "tier",
        "salary_min",
        "salary_max",
        "currency",
        "location",
        "remote",
        "auto_assessment",
    ):
        setattr(posting, f, getattr(body, f))


@router.post("", status_code=201, response_model=PostingOut)
def create_posting(
    body: PostingIn, user: User = Depends(current_recruiter), db: Session = Depends(get_db)
) -> PostingOut:
    posting = JobPosting(recruiter_id=user.id, status=PostingStatus(body.status or "draft"))
    _apply(posting, body)
    db.add(posting)
    db.flush()
    if posting.status == PostingStatus.open:
        enqueue(db, user, JobKind.embed_posting, {"posting_id": posting.id})  # commits both
    else:
        db.commit()
    return _out(posting, owner=True)


@router.get("/mine", response_model=list[PostingOut])
def my_postings(
    user: User = Depends(current_recruiter), db: Session = Depends(get_db)
) -> list[PostingOut]:
    rows = db.scalars(
        select(JobPosting)
        .where(JobPosting.recruiter_id == user.id)
        .order_by(JobPosting.created_at.desc())
    )
    return [_out(p, owner=True) for p in rows]


@router.get("/{posting_id}", response_model=PostingOut)
def get_posting(
    posting_id: str, user: User = Depends(auth.current_user), db: Session = Depends(get_db)
) -> PostingOut:
    posting = db.scalar(  # another world's posting is a 404, same as a missing one
        same_world(
            select(JobPosting).where(JobPosting.id == posting_id), JobPosting.recruiter_id, user
        )
    )
    owner = posting is not None and posting.recruiter_id == user.id
    if posting is None or not (owner or posting.status == PostingStatus.open):
        raise HTTPException(404, "not found")
    return _out(posting, owner=owner)


@router.put("/{posting_id}", response_model=PostingOut)
def update_posting(
    posting_id: str,
    body: PostingIn,
    user: User = Depends(current_recruiter),
    db: Session = Depends(get_db),
) -> PostingOut:
    posting = auth.get_owned(db, JobPosting, posting_id, user)
    if posting.status == PostingStatus.closed:
        raise HTTPException(409, "posting is closed")
    if body.status == "draft" and posting.status == PostingStatus.open:
        raise HTTPException(409, "an open posting cannot go back to draft")
    was_open, before = posting.status == PostingStatus.open, posting_fingerprint(posting)
    _apply(posting, body)
    if body.status == "open":
        posting.status = PostingStatus.open
    if posting.status == PostingStatus.open and (
        not was_open or posting_fingerprint(posting) != before
    ):
        enqueue(db, user, JobKind.embed_posting, {"posting_id": posting.id})  # commits both
    else:
        db.commit()
    return _out(posting, owner=True)


@router.post("/{posting_id}/close", response_model=PostingOut)
def close_posting(
    posting_id: str, user: User = Depends(current_recruiter), db: Session = Depends(get_db)
) -> PostingOut:
    posting = auth.get_owned(db, JobPosting, posting_id, user)
    posting.status = PostingStatus.closed
    db.commit()
    return _out(posting, owner=True)
