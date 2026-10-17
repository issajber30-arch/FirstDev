# Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform.
import logging
import signal
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from firstdev.errors import TransientError
from firstdev.github import GitHubError
from firstdev.llm import LLM, LLMError
from firstdev.models import Job, JobKind, JobStatus, User
from firstdev.worlds import sweep_expired

log = logging.getLogger("firstdev.jobs")

MAX_ATTEMPTS = 3
BACKOFF_BASE_SECONDS = 30
MAX_BACKOFF_SECONDS = 60 * 60
SWEEP_INTERVAL_SECONDS = 10 * 60  # expired sandbox worlds are deleted this often
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


def enqueue_embed_profile(db: Session, profile_id: str) -> Job | None:
    """Queue an embed_profile job for the profile's owner unless one is already waiting."""
    user = db.get(User, profile_id)  # developer_profiles.user_id is the user's id
    if user is None:
        return None
    payload = {"profile_id": profile_id}
    pending = db.scalars(
        select(Job).where(
            Job.user_id == user.id,
            Job.kind == JobKind.embed_profile,
            Job.status == JobStatus.queued,
        )
    ).all()
    if any(j.payload == payload for j in pending):
        return None
    return enqueue(db, user, JobKind.embed_profile, payload)


def claim_next(db: Session, *, now: datetime | None = None) -> Job | None:
    # shortcut: single worker only; upgrade to Postgres SKIP LOCKED when we need >1 worker.
    oldest = (
        select(Job.id)
        .where(
            Job.status == JobStatus.queued,
            or_(Job.run_after.is_(None), Job.run_after <= (now or datetime.now(UTC))),
        )
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


def retry_delay(exc: TransientError, attempts: int) -> float:
    """Exponential backoff, but never sooner than the remote service asked for."""
    backoff = BACKOFF_BASE_SECONDS * 2 ** (attempts - 1)
    return min(max(backoff, exc.retry_after or 0), MAX_BACKOFF_SECONDS)


def _safe_error(exc: Exception) -> str:
    # Only our own exception types carry vetted messages; third-party text may echo user data.
    if isinstance(exc, LLMError | GitHubError | ValueError) and type(exc).__module__.startswith(
        "firstdev"
    ):
        return f"{type(exc).__name__}: {exc}"[:500]
    return type(exc).__name__[:500]


def run_once(db_factory: Callable[[], Session], handlers: dict[JobKind, Handler], llm: LLM) -> bool:
    with db_factory() as db:
        job = claim_next(db)
        if job is None:
            return False
        job_id, kind = job.id, job.kind
        status, error, run_after = JobStatus.done, None, None
        try:
            handler = handlers.get(kind)
            if handler is None:
                raise LookupError(f"no handler for {kind}")
            handler(db, job, llm)
        except Exception as exc:
            db.rollback()  # discard half-done handler work before recording status
            error = _safe_error(exc)
            retry = isinstance(exc, TransientError) and job.attempts < MAX_ATTEMPTS
            status = JobStatus.queued if retry else JobStatus.failed
            if retry:
                run_after = datetime.now(UTC) + timedelta(seconds=retry_delay(exc, job.attempts))
            log.warning("job %s kind=%s failed: %s", job_id, kind, error)
        # Status goes in its own transaction so a handler crash can't lose it.
        # A plain UPDATE matches 0 rows if the owner deleted their account mid-run.
        db.execute(
            update(Job)
            .where(Job.id == job_id)
            .values(status=status, last_error=error, locked_at=None, run_after=run_after)
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
    last_sweep = -SWEEP_INTERVAL_SECONDS  # time-based (not per iteration): runs on startup, then
    while not stop:  # every 10 minutes whether the queue is busy or idle
        if i % 30 == 0:
            with db_factory() as db:
                requeue_stale(db)
        i += 1
        if time.monotonic() - last_sweep >= SWEEP_INTERVAL_SECONDS:
            last_sweep = time.monotonic()
            try:
                with db_factory() as db:
                    sweep_expired(db)
            except Exception:  # a failed sweep is retried next interval; never kill the worker
                log.exception("sandbox sweep failed")
        try:
            worked = run_once(db_factory, handlers, llm)
        except Exception:  # e.g. SQLite "database is locked": keep the worker alive
            log.exception("worker iteration failed")
            worked = False
        if not worked:
            time.sleep(1)
