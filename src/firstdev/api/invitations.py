# Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform.
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from firstdev import auth
from firstdev.api.postings import current_recruiter
from firstdev.api.profiles import current_profile
from firstdev.db import get_db
from firstdev.models import (
    DeveloperProfile,
    Invitation,
    InvitationStatus,
    JobPosting,
    PostingStatus,
    User,
)
from firstdev.worlds import same_world

router = APIRouter()

DAILY_INVITES = 20


class InviteIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    profile_id: str = Field(min_length=1, max_length=36)


class InvitationOut(BaseModel):
    id: str
    posting_id: str
    title: str
    status: InvitationStatus
    created_at: datetime


@router.post("/postings/{posting_id}/invite", status_code=201)
def invite(
    posting_id: str,
    body: InviteIn,
    user: User = Depends(current_recruiter),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    posting = auth.get_owned(db, JobPosting, posting_id, user)
    if posting.status != PostingStatus.open:
        raise HTTPException(409, "posting is not open")
    # Missing and opted-out targets share one response so this can't be used to probe who exists.
    target = db.scalar(
        same_world(
            select(DeveloperProfile).where(DeveloperProfile.user_id == body.profile_id),
            DeveloperProfile.user_id,
            user,
        )
    )
    if target is None or not target.open_to_opportunities:
        raise HTTPException(404, "not found")
    since = datetime.now(UTC) - timedelta(hours=24)
    sent = db.scalar(
        select(func.count())
        .select_from(Invitation)
        .where(Invitation.recruiter_id == user.id, Invitation.created_at > since)
    )
    if sent >= DAILY_INVITES:
        raise HTTPException(429, "daily invitation limit reached")
    inv = Invitation(posting_id=posting.id, profile_id=target.user_id, recruiter_id=user.id)
    db.add(inv)
    try:
        db.commit()
    except IntegrityError:  # unique (posting, profile)
        db.rollback()
        raise HTTPException(409, "already invited") from None
    return {"invitation_id": inv.id}


@router.get("/me/invitations", response_model=list[InvitationOut])
def my_invitations(
    user: User = Depends(auth.current_user),
    profile: DeveloperProfile = Depends(current_profile),
    db: Session = Depends(get_db),
) -> list[InvitationOut]:
    rows = db.execute(
        same_world(  # defence in depth: the inviting posting must be in the caller's world
            select(Invitation, JobPosting.title)
            .join(JobPosting, JobPosting.id == Invitation.posting_id)
            .where(Invitation.profile_id == profile.user_id)
            .order_by(Invitation.created_at.desc()),
            JobPosting.recruiter_id,
            user,
        )
    )
    return [
        InvitationOut(
            id=i.id, posting_id=i.posting_id, title=t, status=i.status, created_at=i.created_at
        )
        for i, t in rows
    ]


@router.post("/invitations/{invitation_id}/decline")
def decline(
    invitation_id: str,
    user: User = Depends(auth.current_user),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    inv = auth.get_owned(db, Invitation, invitation_id, user)  # matches on profile_id: invitee only
    if inv.status != InvitationStatus.sent:
        raise HTTPException(409, f"invitation is already {inv.status}")
    inv.status = InvitationStatus.declined
    db.commit()
    return {"invitation_id": inv.id, "status": inv.status}
