# Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform.
"""POST /demo/sandbox: Turnstile -> per-IP limit -> clone the demo world -> session cookies."""

import hashlib
import logging
from datetime import UTC, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from firstdev import auth, sessions
from firstdev.config import get_settings
from firstdev.db import get_db
from firstdev.demo import clone, turnstile
from firstdev.models import SandboxCreation

router = APIRouter()
log = logging.getLogger("firstdev.demo")

PER_IP_PER_DAY = 3


class SandboxIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["developer", "recruiter"]
    turnstile_token: str = Field(default="", max_length=2048)


class SandboxOut(BaseModel):
    role: str
    world_id: str
    expires_at: datetime


def ip_hash(ip: str) -> str:
    """The only form in which an address is stored; the JWT secret salts it."""
    secret = get_settings().jwt_secret.get_secret_value()
    return hashlib.sha256((ip + secret).encode()).hexdigest()


@router.post("/demo/sandbox", status_code=201, response_model=SandboxOut)
def create_sandbox(
    body: SandboxIn, request: Request, response: Response, db: Session = Depends(get_db)
) -> SandboxOut:
    ip = auth.client_ip(request)
    turnstile.verify(body.turnstile_token, ip)
    h = ip_hash(ip)
    since = datetime.now(UTC) - timedelta(hours=24)
    recent = db.scalar(
        select(func.count())
        .select_from(SandboxCreation)
        .where(SandboxCreation.ip_hash == h, SandboxCreation.created_at > since)
    )
    if recent >= PER_IP_PER_DAY:
        raise HTTPException(429, "sandbox limit reached for today, try again tomorrow")
    try:
        user = clone.create_sandbox(db, body.role, h)
    except Exception as exc:  # all-or-nothing: nothing of a half-built world survives
        db.rollback()
        log.error("sandbox clone failed: %s", type(exc).__name__)  # class only, never the text
        raise HTTPException(500, "could not create the sandbox") from None
    sessions.issue_session(db, response, user)
    return SandboxOut(role=body.role, world_id=user.world_id, expires_at=user.expires_at)
