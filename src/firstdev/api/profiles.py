# Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform.
import re
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import AfterValidator, BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
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


_HANDLE = re.compile(r"[a-z0-9](?:[a-z0-9-]{1,28}[a-z0-9])")
RESERVED_HANDLES = frozenset(
    "admin api demo u me login auth register logout assessments postings applications "
    "connections profiles jobs health docs".split()
)


def normalize_handle(v: str) -> str | None:
    """Lowercased handle, or None if it is not a valid, unreserved handle. ASCII only, so
    lowercasing can't fold look-alike characters (e.g. the Kelvin sign) into a real name."""
    v = v.strip()
    if not v.isascii():
        return None
    v = v.lower()
    return v if _HANDLE.fullmatch(v) and v not in RESERVED_HANDLES else None


def _handle(v: str) -> str:
    if (h := normalize_handle(v)) is None:
        raise ValueError("handle must be 3-30 letters, digits or hyphens (no leading/trailing -)")
    return h


class ProfileIn(BaseModel):
    """PUT replaces the profile: omitted or null fields are cleared."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    headline: str | None = Field(None, min_length=1, max_length=120)
    bio: str | None = Field(None, min_length=1, max_length=2000)
    location: str | None = Field(None, min_length=1, max_length=100)
    experience_tier: Tier | None = None
    github_username: Annotated[str, AfterValidator(_github_username)] | None = None
    open_to_opportunities: bool = False
    handle: Annotated[str, AfterValidator(_handle)] | None = None
    public_profile: bool = False  # opt-in: developers in the real world only


class ProfileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    headline: str | None
    bio: str | None
    location: str | None
    experience_tier: Tier | None
    github_username: str | None
    open_to_opportunities: bool
    handle: str | None = None
    public_profile: bool = False


def current_profile(
    user: User = Depends(auth.current_user), db: Session = Depends(get_db)
) -> DeveloperProfile:
    profile = db.get(DeveloperProfile, user.id)
    if profile is None:  # recruiters have no profile
        raise HTTPException(404, "not found")
    return profile


def _out(profile: DeveloperProfile, user: User) -> ProfileOut:
    out = ProfileOut.model_validate(profile)
    return out.model_copy(update={"handle": user.handle, "public_profile": user.public_profile})


@router.get("/me", response_model=ProfileOut)
def get_profile(
    user: User = Depends(auth.current_user), profile: DeveloperProfile = Depends(current_profile)
) -> ProfileOut:
    return _out(profile, user)


@router.put("/me", response_model=ProfileOut)
def put_profile(
    body: ProfileIn,
    user: User = Depends(auth.current_user),
    profile: DeveloperProfile = Depends(current_profile),
    db: Session = Depends(get_db),
) -> ProfileOut:
    # Handles are unique across worlds, so a sandbox setting one could probe which handles real
    # users hold. Sandboxes are temporary and never public: they get no handle.
    if user.world_id is not None and body.handle is not None:
        raise HTTPException(422, "sandbox profiles cannot have a handle")
    if body.public_profile:
        # Developers only (current_profile already 404s recruiters), real world only.
        if user.world_id is not None:
            raise HTTPException(422, "sandbox profiles cannot be public")
        if body.handle is None:
            raise HTTPException(422, "choose a handle before making the profile public")
    if body.handle is not None and db.scalar(
        select(User.id).where(User.handle == body.handle, User.id != user.id)
    ):
        raise HTTPException(409, "handle is taken")
    for field, value in body.model_dump(exclude={"handle", "public_profile"}).items():
        setattr(profile, field, value)
    user.handle, user.public_profile = body.handle, body.public_profile
    try:
        db.commit()
    except IntegrityError:  # a concurrent claim of the same handle
        db.rollback()
        raise HTTPException(409, "handle is taken") from None
    return _out(profile, user)
