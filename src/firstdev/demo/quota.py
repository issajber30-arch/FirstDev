# Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform.
"""Per-sandbox AI quotas, counted from the jobs table across every user of the world.

Real users (world_id NULL) are never limited here. Jobs killed by the global budget refusal do
not use up the quota: the visitor got nothing for them. Assessments are counted by their
generation job (one per assessment, however it was triggered); the fixture's own graded
assessment is inserted directly and so is not counted.
"""

from fastapi import HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from firstdev.models import Job, JobKind, JobStatus, User

LIMITS = {"cv_parse": 1, "repo_analyze": 1, "assessment": 1, "score_pair": 4, "rank_posting": 2}
_BUDGET_REFUSAL = "demo AI budget reached"


def check(db: Session, user: User, kind: str) -> None:
    """Raise 429 when the user's sandbox world has used up `kind`; no-op outside sandboxes."""
    if user.world_id is None:
        return
    job_kind = JobKind.assessment_generate if kind == "assessment" else JobKind(kind)
    q = (
        select(func.count())
        .select_from(Job)
        .join(User, User.id == Job.user_id)
        .where(
            User.world_id == user.world_id,
            Job.kind == job_kind,
            or_(
                Job.status != JobStatus.failed,
                Job.last_error.is_(None),
                ~Job.last_error.contains(_BUDGET_REFUSAL),
            ),
        )
    )
    if kind == "score_pair":  # only explaining scores cost LLM calls
        q = q.where(Job.payload["explain"].as_boolean().is_(True))
    if db.scalar(q) >= LIMITS[kind]:
        raise HTTPException(429, "demo limit reached for this sandbox")
