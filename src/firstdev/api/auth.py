# Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform.
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from firstdev import auth, invites, sessions
from firstdev.config import get_settings
from firstdev.db import get_db
from firstdev.models import DeveloperProfile, RefreshToken, Role, User
from firstdev.security.sanitize import EmptyInput, InputTooLarge, sanitize_text

router = APIRouter()


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RegisterIn(_In):
    email: EmailStr = Field(max_length=254)
    # Passwords are never stripped: whitespace may be deliberate.
    password: str = Field(min_length=12, max_length=128)
    role: Literal["developer", "recruiter"]
    # Required here, nullable in the DB (pre-Part 4 users have none).
    display_name: str = Field(max_length=200)
    invite_code: str | None = Field(default=None, max_length=64)

    @field_validator("display_name")
    @classmethod
    def _clean_name(cls, v: str) -> str:
        try:
            v = sanitize_text(v, max_chars=60)
        except (EmptyInput, InputTooLarge) as e:
            raise ValueError("display_name must be 1-60 characters") from e
        return " ".join(v.split())  # newlines/tabs have no place in a name


class LoginIn(_In):
    email: str = Field(max_length=254)
    password: str = Field(max_length=128)


class DeleteMeIn(_In):
    password: str = Field(max_length=128)


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"  # noqa: S105


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    email: str
    role: Role
    display_name: str | None


@router.post("/auth/register", response_model=UserOut, status_code=201)
def register(body: RegisterIn, request: Request, db: Session = Depends(get_db)) -> User:
    email = body.email.lower()
    invite = None
    if get_settings().require_invite:
        ip_key = auth.limiter_keys(request, email)[0]
        if auth.login_limiter.blocked(ip_key):
            raise HTTPException(429, "too many failed attempts, try again later")
        invite = invites.consume(db, body.invite_code or "")
        if invite is None:  # same answer for unknown, used and revoked codes
            auth.login_limiter.fail(ip_key)
            raise HTTPException(403, "invalid invite code")
    if db.scalar(select(User.id).where(User.email == email)):
        db.rollback()  # a duplicate email must not burn the invite
        raise HTTPException(409, "registration failed")
    user = User(
        email=email,
        password_hash=auth.hash_password(body.password),
        role=body.role,
        display_name=body.display_name,
    )
    db.add(user)
    try:
        db.flush()
        if invite is not None:
            invite.used_by = user.id
        if user.role == Role.developer:
            db.add(DeveloperProfile(user_id=user.id))
        db.commit()
    except IntegrityError:  # concurrent registration of the same email
        db.rollback()
        raise HTTPException(409, "registration failed") from None
    return user


@router.post("/auth/login", response_model=TokenOut)
def login(
    body: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)
) -> TokenOut:
    email = body.email.strip().lower()
    ip_key, email_key = auth.limiter_keys(request, email)
    if auth.login_limiter.blocked(ip_key, email_key):
        raise HTTPException(429, "too many failed attempts, try again later")
    user = db.scalar(select(User).where(User.email == email))
    if user is None:
        auth.verify_dummy(body.password)
        ok = False
    else:
        ok = auth.verify_password(user.password_hash, body.password)
    if not ok:
        auth.login_limiter.fail(ip_key, email_key)
        raise HTTPException(401, auth.LOGIN_ERROR)
    auth.login_limiter.clear(email_key)
    return TokenOut(access_token=sessions.issue_session(db, response, user))


@router.post("/auth/refresh", status_code=204)
def refresh(request: Request, response: Response, db: Session = Depends(get_db)) -> None:
    # Cookie only, and deliberately independent of the (possibly expired) access cookie.
    raw = request.cookies.get(sessions.REFRESH)
    if not raw:
        raise HTTPException(401, "invalid refresh token", headers={"WWW-Authenticate": "Bearer"})
    sessions.rotate(db, response, raw)


@router.post("/auth/logout", status_code=204)
def logout(request: Request, response: Response, db: Session = Depends(get_db)) -> None:
    raw = request.cookies.get(sessions.REFRESH)
    row = (
        db.scalar(select(RefreshToken).where(RefreshToken.token_hash == sessions.hash_token(raw)))
        if raw
        else None
    )
    if row is not None:
        sessions.revoke_family(db, row.family_id)
    sessions.clear_cookies(response)


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(auth.current_user)) -> User:
    return user


@router.delete("/me", status_code=204)
def delete_me(
    body: DeleteMeIn,
    request: Request,
    response: Response,
    user: User = Depends(auth.current_user),
    db: Session = Depends(get_db),
) -> None:
    # A stolen token must not be enough to wipe the account, so the password is re-checked
    # (and rate-limited like login).
    keys = auth.limiter_keys(request, user.email)
    if auth.login_limiter.blocked(*keys):
        raise HTTPException(429, "too many failed attempts, try again later")
    if not auth.verify_password(user.password_hash, body.password):
        auth.login_limiter.fail(*keys)
        raise HTTPException(403, "invalid password")
    db.delete(user)  # the database cascades to everything the user owns
    db.commit()
    sessions.clear_cookies(response)
