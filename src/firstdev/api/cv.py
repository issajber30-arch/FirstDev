# Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform.
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from firstdev import auth
from firstdev.api.profiles import current_profile
from firstdev.db import get_db
from firstdev.jobs import enqueue
from firstdev.models import CvDocument, CvParse, CvStatus, DeveloperProfile, Job, JobKind, User
from firstdev.pipelines.cv_parser import prepare_text
from firstdev.security.sanitize import EmptyInput, InputTooLarge
from firstdev.security.uploads import PDF_MAX, UploadRejected

router = APIRouter()

DAILY_QUOTA = 10
# Rejected uploads store nothing, so the daily quota can't see them; this caps the PDF
# subprocess work a user can trigger with bad files.
rejected_uploads = auth.FailureLimiter(max_failures=20, window_seconds=60 * 60)


class CvQueued(BaseModel):
    cv_id: str
    job_id: str | None
    status: CvStatus


class CvOut(BaseModel):
    id: str
    status: CvStatus
    created_at: datetime
    page_count: int | None
    injection_flags: list | None
    parse: dict | None  # extracted_text is internal and never returned (PII)


@router.post("/profiles/me/cv", status_code=202, response_model=CvQueued)
def upload_cv(
    response: Response,
    file: Annotated[UploadFile | None, File()] = None,
    text: Annotated[str | None, Form()] = None,
    user: User = Depends(auth.current_user),
    profile: DeveloperProfile = Depends(current_profile),
    db: Session = Depends(get_db),
) -> CvQueued:
    if (file is None) == (text is None):
        raise HTTPException(422, "send exactly one of 'file' or 'text'")
    # Quota first: it is cheap and runs before the expensive PDF extraction.
    since = datetime.now(UTC) - timedelta(hours=24)
    recent = db.scalar(
        select(func.count())
        .select_from(CvDocument)
        .where(CvDocument.profile_id == profile.user_id, CvDocument.created_at > since)
    )
    if recent >= DAILY_QUOTA:
        raise HTTPException(429, "daily CV upload limit reached")
    reject_key = f"user:{user.id}"
    if rejected_uploads.blocked(reject_key):
        raise HTTPException(429, "too many rejected uploads, try again later")

    # Hard cap on bytes read; Content-Length is never trusted.
    raw = file.file.read(PDF_MAX + 1) if file is not None else text.encode("utf-8")
    try:
        if len(raw) > PDF_MAX:
            raise HTTPException(413, "file too large")
        try:
            cv_text, meta, flags = prepare_text(raw)
        except InputTooLarge:
            raise HTTPException(413, "CV text too large") from None
        except EmptyInput:
            raise HTTPException(422, "no text content") from None
        except UploadRejected as e:
            raise HTTPException(413 if str(e).endswith("too large") else 422, str(e)) from None
    except HTTPException:
        rejected_uploads.fail(reject_key)
        raise

    existing = db.scalar(
        select(CvDocument).where(
            CvDocument.profile_id == profile.user_id,
            CvDocument.sha256 == meta["sha256"],
            CvDocument.status.in_([CvStatus.pending, CvStatus.parsed]),
        )
    )
    if existing is not None:
        job_id = db.scalar(
            select(Job.id)
            .where(
                Job.user_id == user.id,
                Job.kind == JobKind.cv_parse,
                Job.payload["cv_document_id"].as_string() == existing.id,
            )
            .order_by(Job.created_at.desc())
            .limit(1)
        )
        response.status_code = 200
        return CvQueued(cv_id=existing.id, job_id=job_id, status=existing.status)

    doc = CvDocument(
        profile_id=profile.user_id,
        sha256=meta["sha256"],
        size=meta["size"],
        page_count=meta["page_count"],
        status=CvStatus.pending,
        extracted_text=cv_text,
        injection_flags=flags,
    )
    db.add(doc)
    db.flush()
    # The payload is only an id: CV text never goes into the jobs table. enqueue() commits both.
    job = enqueue(db, user, JobKind.cv_parse, {"cv_document_id": doc.id})
    return CvQueued(cv_id=doc.id, job_id=job.id, status=doc.status)


@router.get("/cv/{cv_id}", response_model=CvOut)
def get_cv(
    cv_id: str, user: User = Depends(auth.current_user), db: Session = Depends(get_db)
) -> CvOut:
    doc = auth.get_owned(db, CvDocument, cv_id, user)
    parse = db.scalar(
        select(CvParse)
        .where(CvParse.cv_document_id == doc.id)
        .order_by(CvParse.created_at.desc())
        .limit(1)
    )
    return CvOut(
        id=doc.id,
        status=doc.status,
        created_at=doc.created_at,
        page_count=doc.page_count,
        injection_flags=doc.injection_flags,
        parse=parse.data if parse else None,
    )


@router.delete("/cv/{cv_id}", status_code=204)
def delete_cv(
    cv_id: str, user: User = Depends(auth.current_user), db: Session = Depends(get_db)
) -> Response:
    db.delete(auth.get_owned(db, CvDocument, cv_id, user))  # the database cascades to parses
    db.commit()
    return Response(status_code=204)
