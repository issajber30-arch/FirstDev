# Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform.
"""Cloudflare Turnstile server-side verification (fixed URL, short timeout, fail closed)."""

import logging

import httpx
from fastapi import HTTPException

from firstdev.config import get_settings

log = logging.getLogger("firstdev.turnstile")

VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"
TIMEOUT_SECONDS = 5.0


def verify(token: str, ip: str) -> None:
    """Return normally only for a valid token; 403 for a rejected one, 503 when we cannot tell."""
    s = get_settings()
    if s.turnstile_disabled:  # config validation guarantees env != prod here
        return
    secret = s.turnstile_secret.get_secret_value() if s.turnstile_secret else ""
    if not secret:
        raise HTTPException(503, "verification unavailable, try again")
    if not token:
        raise HTTPException(403, "verification failed")
    try:
        r = httpx.post(
            VERIFY_URL,
            data={"secret": secret, "response": token, "remoteip": ip},
            timeout=TIMEOUT_SECONDS,
            follow_redirects=False,
        )
        ok = r.status_code == 200 and r.json().get("success") is True
        unavailable = r.status_code >= 500
    except (httpx.HTTPError, ValueError) as exc:  # network, timeout or a non-JSON answer
        log.warning("turnstile unavailable: %s", type(exc).__name__)
        raise HTTPException(503, "verification unavailable, try again") from None
    if unavailable:
        raise HTTPException(503, "verification unavailable, try again")
    if not ok:
        raise HTTPException(403, "verification failed")
