# Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform.
from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from firstdev import auth
from firstdev.db import get_db
from firstdev.models import Job, JobKind, JobStatus, User

router = APIRouter(prefix="/jobs")


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    kind: JobKind
    status: JobStatus
    attempts: int
    last_error: str | None
    created_at: datetime


@router.get("/{job_id}", response_model=JobOut)
def get_job(
    job_id: str, user: User = Depends(auth.current_user), db: Session = Depends(get_db)
) -> Job:
    return auth.get_owned(db, Job, job_id, user)
