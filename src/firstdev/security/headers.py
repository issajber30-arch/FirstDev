# Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform.
"""ASGI middleware adding hardening headers to every API response (the API serves JSON only)."""

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from firstdev.config import get_settings

_STATIC = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
}
# Swagger UI (dev only) loads scripts from a CDN, which the JSON-only CSP would block.
_DOCS = {"/docs", "/redoc"}


class SecurityHeaders:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        req = dict(scope["headers"])
        # Credentialed requests (and token-issuing /auth responses) must never be cached.
        sensitive = (
            b"authorization" in req or b"cookie" in req or scope["path"].startswith("/auth/")
        )

        async def send_with_headers(msg: Message) -> None:
            if msg["type"] == "http.response.start":
                h = MutableHeaders(scope=msg)
                for k, v in _STATIC.items():
                    if not (k == "Content-Security-Policy" and scope["path"] in _DOCS):
                        h[k] = v
                if get_settings().env == "prod":
                    h["Strict-Transport-Security"] = "max-age=31536000"
                if sensitive and "cache-control" not in h:
                    h["Cache-Control"] = "no-store"
            await send(msg)

        await self.app(scope, receive, send_with_headers)
