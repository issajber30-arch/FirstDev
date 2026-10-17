# Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform.
import re
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import AfterValidator, BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from firstdev import auth
from firstdev.db import get_db
from firstdev.models import DeveloperProfile, Tier, User

router = APIRouter(prefix="/profiles")

# GitHub username rules; checked here because pydantic's regex engine has no lookahead.
_GITHUB_USER = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9]|-(?=[A-Za-z0-9])){0,38}")


def _github_username(v: str) -> str:
    if not _GITHUB_USER.fullmatch(v):
        raise ValueError("invalid GitHub username")
    return v


class ProfileIn(BaseModel):
    """PUT replaces the profile: omitted or null fields are cleared."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    headline: str | None = Field(None, min_length=1, max_length=120)
    bio: str | None = Field(None, min_length=1, max_length=2000)
    location: str | None = Field(None, min_length=1, max_length=100)
    experience_tier: Tier | None = None
    github_username: Annotated[str, AfterValidator(_github_username)] | None = None
    open_to_opportunities: bool = False


class ProfileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    headline: str | None
    bio: str | None
    location: str | None
    experience_tier: Tier | None
    github_username: str | None
    open_to_opportunities: bool


def current_profile(
    user: User = Depends(auth.current_user), db: Session = Depends(get_db)
) -> DeveloperProfile:
    profile = db.get(DeveloperProfile, user.id)
    if profile is None:  # recruiters have no profile
        raise HTTPException(404, "not found")
    return profile


@router.get("/me", response_model=ProfileOut)
def get_profile(profile: DeveloperProfile = Depends(current_profile)) -> DeveloperProfile:
    return profile


@router.put("/me", response_model=ProfileOut)
def put_profile(
    body: ProfileIn,
    profile: DeveloperProfile = Depends(current_profile),
    db: Session = Depends(get_db),
) -> DeveloperProfile:
    for field, value in body.model_dump().items():
        setattr(profile, field, value)
    db.commit()
    return profile
