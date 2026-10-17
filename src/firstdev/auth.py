# Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform.
import time
from collections import defaultdict, deque
from datetime import UTC, datetime, timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from firstdev.config import get_settings
from firstdev.db import get_db
from firstdev.models import User

_hasher = PasswordHasher()
# Verified against when the email is unknown, so both failure paths cost one argon2 verify.
_DUMMY_HASH = _hasher.hash("firstdev-dummy-password")

ALGORITHM = "HS256"
LOGIN_ERROR = "invalid email or password"


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def verify_dummy(password: str) -> None:
    verify_password(_DUMMY_HASH, password)


def create_token(user_id: str) -> str:
    s = get_settings()
    now = datetime.now(UTC)
    claims = {"sub": user_id, "iat": now, "exp": now + timedelta(minutes=s.jwt_ttl_minutes)}
    return jwt.encode(claims, s.jwt_secret.get_secret_value(), algorithm=ALGORITHM)


def decode_token(token: str) -> str:
    """Return the user id, or raise jwt.PyJWTError."""
    claims = jwt.decode(
        token,
        get_settings().jwt_secret.get_secret_value(),
        algorithms=[ALGORITHM],  # pinned: rejects alg=none and algorithm confusion
        options={"require": ["exp", "sub", "iat"]},
    )
    return claims["sub"]


_bearer = HTTPBearer(auto_error=False)


def _unauthorized() -> HTTPException:
    return HTTPException(401, "not authenticated", headers={"WWW-Authenticate": "Bearer"})


def current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User:
    if creds is None:
        raise _unauthorized()
    try:
        user_id = decode_token(creds.credentials)
    except jwt.PyJWTError:
        raise _unauthorized() from None
    user = db.get(User, user_id)
    if user is None:
        raise _unauthorized()
    return user


class FailureLimiter:
    """Sliding window of failed attempts per key."""

    # shortcut: in-memory, per-process; move to shared store when >1 API process
    def __init__(
        self, max_failures: int = 5, window_seconds: int = 15 * 60, max_keys: int = 10_000
    ):
        self.max_failures = max_failures
        self.window = window_seconds
        self.max_keys = max_keys  # bounds memory when many distinct IPs/emails fail
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def _prune(self, key: str) -> deque[float]:
        hits = self._hits[key]
        cutoff = time.monotonic() - self.window
        while hits and hits[0] <= cutoff:
            hits.popleft()
        if not hits:
            del self._hits[key]
        return hits

    def blocked(self, *keys: str) -> bool:
        return any(len(self._prune(k)) >= self.max_failures for k in keys)

    def fail(self, *keys: str) -> None:
        for k in keys:
            self._hits[k].append(time.monotonic())
        if len(self._hits) > self.max_keys:
            for k in list(self._hits):
                self._prune(k)
            # Still over: drop the keys whose latest failure is oldest.
            excess = len(self._hits) - self.max_keys
            if excess > 0:
                for k in sorted(self._hits, key=lambda k: self._hits[k][-1])[:excess]:
                    del self._hits[k]

    def clear(self, key: str) -> None:
        self._hits.pop(key, None)

    def reset(self) -> None:
        self._hits.clear()


login_limiter = FailureLimiter()


def limiter_keys(request: Request, email: str) -> tuple[str, str]:
    # Behind a proxy request.client is the proxy; revisit with trusted forwarded headers.
    ip = request.client.host if request.client else "unknown"
    return f"ip:{ip}", f"email:{email}"


def get_owned[M](db: Session, model: type[M], obj_id: str, user: User) -> M:
    """Fetch a row by id only if the user owns it; 404 for missing and foreign rows alike."""
    col = next(
        (getattr(model, c) for c in ("profile_id", "user_id", "recruiter_id") if hasattr(model, c)),
        None,
    )
    if col is None:
        raise TypeError(f"{model.__name__} has no owner column")
    # profile_id is the owner's user id (developer_profiles.user_id is its primary key)
    row = db.query(model).filter(model.id == obj_id, col == user.id).one_or_none()
    if row is None:
        raise HTTPException(404, "not found")
    return row
