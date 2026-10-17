# Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform.
from fastapi import FastAPI

from firstdev.api import (
    applications,
    assessments,
    auth,
    cv,
    invitations,
    jobs,
    matches,
    postings,
    profiles,
    repos,
)
from firstdev.config import get_settings
from firstdev.security.body_limit import BodySizeLimit
from firstdev.security.headers import SecurityHeaders
from firstdev.security.uploads import PDF_MAX
from firstdev.sessions import CSRFMiddleware


def create_app() -> FastAPI:
    # API docs are only exposed in dev to keep the production surface small.
    is_dev = get_settings().env == "dev"
    app = FastAPI(
        title="FirstDev",
        docs_url="/docs" if is_dev else None,
        redoc_url="/redoc" if is_dev else None,
        openapi_url="/openapi.json" if is_dev else None,
    )

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(auth.router)
    app.include_router(profiles.router)
    app.include_router(jobs.router)
    app.include_router(cv.router)
    app.include_router(repos.router)
    app.include_router(postings.router)
    app.include_router(applications.router)
    app.include_router(invitations.router)
    app.include_router(matches.router)
    app.include_router(assessments.router)
    # Largest legit request is a 5 MB CV plus multipart framing.
    app.add_middleware(CSRFMiddleware)
    app.add_middleware(BodySizeLimit, max_bytes=PDF_MAX + 64 * 1024)
    # Added last = outermost, so even 403/413 rejections from the middlewares get the headers.
    app.add_middleware(SecurityHeaders)
    return app


app = create_app()
