# Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform.
from fastapi import FastAPI

from firstdev.api import auth, cv, jobs, profiles
from firstdev.config import get_settings
from firstdev.security.body_limit import BodySizeLimit
from firstdev.security.uploads import PDF_MAX


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
    # Largest legit request is a 5 MB CV plus multipart framing.
    app.add_middleware(BodySizeLimit, max_bytes=PDF_MAX + 64 * 1024)
    return app


app = create_app()
