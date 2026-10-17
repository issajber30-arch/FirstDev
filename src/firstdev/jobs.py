# Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform.
import logging
import signal
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from firstdev.llm import LLM, LLMError, LLMTransientError
from firstdev.models import Job, JobKind, JobStatus, User

log = logging.getLogger("firstdev.jobs")

MAX_ATTEMPTS = 3
Handler = Callable[[Session, Job, LLM], None]
# Pipelines (M3/M4) register themselves here.
HANDLERS: dict[JobKind, Handler] = {}
# Called when a job ends in `failed` so the pipeline can surface it on its own record.
FAILURE_HOOKS: dict[JobKind, Callable[[Session, Job], None]] = {}


def enqueue(db: Session, user: User, kind: JobKind, payload: dict) -> Job:
    job = Job(user_id=user.id, kind=kind, payload=payload)
    db.add(job)
    db.commit()
    return job


def claim_next(db: Session, *, now: datetime | None = None) -> Job | None:
    # shortcut: single worker only; upgrade to Postgres SKIP LOCKED when we need >1 worker.
    oldest = (
        select(Job.id)
        .where(Job.status == JobStatus.queued)
        .order_by(Job.created_at)
        .limit(1)
        .scalar_subquery()
    )
    stmt = (
        update(Job)
        .where(Job.id == oldest, Job.status == JobStatus.queued)
        .values(
            status=JobStatus.running,
            locked_at=now or datetime.now(UTC),
            attempts=Job.attempts + 1,
        )
        .returning(Job.id)
        .execution_options(synchronize_session=False)
    )
    job_id = db.execute(stmt).scalar_one_or_none()
    db.commit()
    if job_id is None:
        return None
    db.expire_all()  # the Core UPDATE bypassed the identity map
    return db.get(Job, job_id)


def _run_failure_hook(db: Session, job: Job) -> None:
    hook = FAILURE_HOOKS.get(job.kind)
    if hook is None:
        return
    try:
        hook(db, job)
        db.commit()
    except Exception as exc:  # a hook bug must never crash the worker
        db.rollback()
        log.warning("failure hook for job kind=%s raised %s", job.kind, type(exc).__name__)


def requeue_stale(db: Session, *, older_than: timedelta = timedelta(minutes=10)) -> int:
    cutoff = datetime.now(UTC) - older_than
    stale = db.scalars(
        select(Job).where(Job.status == JobStatus.running, Job.locked_at < cutoff)
    ).all()
    gave_up = []
    for job in stale:
        if job.attempts < MAX_ATTEMPTS:
            job.status = JobStatus.queued
        else:
            job.status = JobStatus.failed
            job.last_error = f"gave up after {MAX_ATTEMPTS} attempts"
            gave_up.append(job)
        job.locked_at = None
    db.commit()
    for job in gave_up:
        _run_failure_hook(db, job)
    return len(stale)


def _safe_error(exc: Exception) -> str:
    # Only our own exception types carry vetted messages; third-party text may echo user data.
    if isinstance(exc, LLMError | ValueError) and type(exc).__module__.startswith("firstdev"):
        return f"{type(exc).__name__}: {exc}"[:500]
    return type(exc).__name__[:500]


def run_once(db_factory: Callable[[], Session], handlers: dict[JobKind, Handler], llm: LLM) -> bool:
    with db_factory() as db:
        job = claim_next(db)
        if job is None:
            return False
        job_id, kind = job.id, job.kind
        status, error = JobStatus.done, None
        try:
            handler = handlers.get(kind)
            if handler is None:
                raise LookupError(f"no handler for {kind}")
            handler(db, job, llm)
        except Exception as exc:
            db.rollback()  # discard half-done handler work before recording status
            error = _safe_error(exc)
            retry = isinstance(exc, LLMTransientError) and job.attempts < MAX_ATTEMPTS
            status = JobStatus.queued if retry else JobStatus.failed
            log.warning("job %s kind=%s failed: %s", job_id, kind, error)
        # Status goes in its own transaction so a handler crash can't lose it.
        # A plain UPDATE matches 0 rows if the owner deleted their account mid-run.
        db.execute(
            update(Job)
            .where(Job.id == job_id)
            .values(status=status, last_error=error, locked_at=None)
            .execution_options(synchronize_session=False)
        )
        db.commit()
        if status == JobStatus.failed:
            _run_failure_hook(db, job)
        return True


def worker_main(
    db_factory: Callable[[], Session], llm: LLM, *, handlers: dict[JobKind, Handler] | None = None
) -> None:
    stop = False

    def _stop(*_):
        nonlocal stop
        stop = True

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)
    handlers = HANDLERS if handlers is None else handlers
    i = 0
    while not stop:
        if i % 30 == 0:
            with db_factory() as db:
                requeue_stale(db)
        i += 1
        try:
            worked = run_once(db_factory, handlers, llm)
        except Exception:  # e.g. SQLite "database is locked": keep the worker alive
            log.exception("worker iteration failed")
            worked = False
        if not worked:
            time.sleep(1)
