# Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform.
"""Cookie sessions: access JWT + rotating opaque refresh token + CSRF double-submit token."""

import hashlib
import hmac
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, Response
from sqlalchemy import select, update
from sqlalchemy.orm import Session
from starlette.requests import cookie_parser
from starlette.types import ASGIApp, Receive, Scope, Send

from firstdev import auth
from firstdev.config import get_settings
from firstdev.models import RefreshToken, User

ACCESS, REFRESH, CSRF = "fd_access", "fd_refresh", "fd_csrf"
UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}
# Login has no session yet; refresh is SameSite=Strict on a narrow path; sandbox creation is
# protected by Turnstile.
CSRF_EXEMPT = {"/auth/login", "/auth/refresh", "/auth/register", "/demo/sandbox"}
CSRF_ERROR = b'{"detail":"CSRF token missing or invalid"}'


def _refresh_path() -> str:
    # Browsers only send the refresh cookie under this path: "/api" behind the Next.js proxy,
    # "" when the API is reached directly (dev, scripts).
    return f"{get_settings().cookie_path_prefix}/auth"


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def _set_cookies(response: Response, access: str, refresh: str | None) -> None:
    s = get_settings()
    secure = s.cookie_secure
    ttl = s.refresh_ttl_days * 86400
    response.set_cookie(
        ACCESS,
        access,
        max_age=s.jwt_ttl_minutes * 60,
        path="/",
        httponly=True,
        secure=secure,
        samesite="lax",
    )
    if refresh is not None:
        response.set_cookie(
            REFRESH,
            refresh,
            max_age=ttl,
            path=_refresh_path(),
            httponly=True,
            secure=secure,
            samesite="strict",
        )
    # Not httpOnly: the frontend reads it and echoes it in X-CSRF-Token.
    response.set_cookie(
        CSRF,
        secrets.token_urlsafe(32),
        max_age=ttl,
        path="/",
        httponly=False,
        secure=secure,
        samesite="strict",
    )


def clear_cookies(response: Response) -> None:
    secure = get_settings().cookie_secure
    for name, path, samesite in (
        (ACCESS, "/", "lax"),
        (REFRESH, _refresh_path(), "strict"),
        (CSRF, "/", "strict"),
    ):
        response.delete_cookie(
            name, path=path, httponly=name != CSRF, secure=secure, samesite=samesite
        )


def _new_refresh(db: Session, user_id: str, family_id: str) -> str:
    raw = secrets.token_urlsafe(32)
    ttl = timedelta(days=get_settings().refresh_ttl_days)
    db.add(
        RefreshToken(
            user_id=user_id,
            family_id=family_id,
            token_hash=hash_token(raw),
            expires_at=datetime.now(UTC) + ttl,
        )
    )
    return raw


def issue_session(db: Session, response: Response, user: User) -> str:
    """Start a new refresh family, set the three cookies, return the access token."""
    raw = _new_refresh(db, user.id, str(uuid.uuid4()))
    db.commit()
    access = auth.create_token(user.id)
    _set_cookies(response, access, raw)
    return access


def revoke_family(db: Session, family_id: str) -> None:
    db.execute(
        update(RefreshToken)
        .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
    )
    db.commit()


def _invalid() -> HTTPException:
    return HTTPException(401, "invalid refresh token", headers={"WWW-Authenticate": "Bearer"})


def rotate(db: Session, response: Response, raw_refresh: str) -> User:
    """Exchange a refresh token for a new one in the same family and reset the cookies."""
    now = datetime.now(UTC)
    row = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == hash_token(raw_refresh)))
    if row is None or row.revoked_at is not None:
        raise _invalid()
    if row.used_at is not None:
        # Trade-off (accepted): two tabs refreshing with the same token look identical to
        # a stolen-token replay, so the loser revokes the family and both tabs log out.
        revoke_family(db, row.family_id)
        raise _invalid()
    if row.expires_at <= now:
        raise _invalid()
    # Atomic claim: of two concurrent requests only one sees rowcount 1; the other is reuse.
    claimed = db.execute(
        update(RefreshToken)
        .where(RefreshToken.id == row.id, RefreshToken.used_at.is_(None))
        .values(used_at=now)
    )
    if claimed.rowcount != 1:
        revoke_family(db, row.family_id)
        raise _invalid()
    user = db.get(User, row.user_id)
    if user is None:
        raise _invalid()
    raw = _new_refresh(db, user.id, row.family_id)
    db.commit()
    _set_cookies(response, auth.create_token(user.id), raw)
    return user


class CSRFMiddleware:
    """Double-submit check for unsafe requests authenticated by the fd_access cookie."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and self._needs_check(scope) and not self._valid(scope):
            await send(
                {
                    "type": "http.response.start",
                    "status": 403,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"content-length", str(len(CSRF_ERROR)).encode()),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": CSRF_ERROR})
            return
        await self.app(scope, receive, send)

    @staticmethod
    def _needs_check(scope: Scope) -> bool:
        if scope["method"] not in UNSAFE or scope["path"] in CSRF_EXEMPT:
            return False
        headers = dict(scope["headers"])
        # Only a Bearer header replaces the cookie; any other scheme falls back to the cookie
        # in current_user, so it must not skip the CSRF check.
        if headers.get(b"authorization", b"").lower().startswith(b"bearer "):
            return False
        return ACCESS in cookie_parser(headers.get(b"cookie", b"").decode("latin-1"))

    @staticmethod
    def _valid(scope: Scope) -> bool:
        headers = dict(scope["headers"])
        cookie = cookie_parser(headers.get(b"cookie", b"").decode("latin-1")).get(CSRF, "")
        sent = headers.get(b"x-csrf-token", b"").decode("latin-1")
        return bool(cookie) and hmac.compare_digest(cookie.encode(), sent.encode())
