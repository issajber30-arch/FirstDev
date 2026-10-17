# Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform.
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from firstdev import auth
from firstdev.db import get_db
from firstdev.models import DeveloperProfile, Role, User

router = APIRouter()


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RegisterIn(_In):
    email: EmailStr = Field(max_length=254)
    # Passwords are never stripped: whitespace may be deliberate.
    password: str = Field(min_length=12, max_length=128)
    role: Literal["developer", "recruiter"]


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


@router.post("/auth/register", response_model=UserOut, status_code=201)
def register(body: RegisterIn, db: Session = Depends(get_db)) -> User:
    email = body.email.lower()
    if db.scalar(select(User.id).where(User.email == email)):
        raise HTTPException(409, "registration failed")
    user = User(email=email, password_hash=auth.hash_password(body.password), role=body.role)
    db.add(user)
    try:
        db.flush()
        if user.role == Role.developer:
            db.add(DeveloperProfile(user_id=user.id))
        db.commit()
    except IntegrityError:  # concurrent registration of the same email
        db.rollback()
        raise HTTPException(409, "registration failed") from None
    return user


@router.post("/auth/login", response_model=TokenOut)
def login(body: LoginIn, request: Request, db: Session = Depends(get_db)) -> TokenOut:
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
    return TokenOut(access_token=auth.create_token(user.id))


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(auth.current_user)) -> User:
    return user


@router.delete("/me", status_code=204)
def delete_me(
    body: DeleteMeIn,
    request: Request,
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
