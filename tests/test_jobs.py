# Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform.
import sqlite3
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from firstdev.jobs import claim_next, enqueue, requeue_stale, run_once
from firstdev.llm import FakeLLM, LLMPermanentError, LLMTransientError
from firstdev.models import Job, JobKind, JobStatus, Role, User


@pytest.fixture
def user(db):
    u = User(email="u@example.com", password_hash="x", role=Role.developer)
    db.add(u)
    db.commit()
    return u


@pytest.fixture
def factory(engine):
    return sessionmaker(engine, expire_on_commit=False)


def test_sqlite_supports_returning():
    assert sqlite3.sqlite_version_info >= (3, 35)


def test_enqueue_claim_order(db, user):
    a = enqueue(db, user, JobKind.cv_parse, {"n": 1})
    b = enqueue(db, user, JobKind.repo_analyze, {"n": 2})
    j1 = claim_next(db)
    assert (j1.id, j1.status, j1.attempts) == (a.id, JobStatus.running, 1)
    assert j1.locked_at is not None
    assert claim_next(db).id == b.id
    assert claim_next(db) is None


def test_requeue_stale(db, user):
    old = datetime.now(UTC) - timedelta(minutes=30)
    j = enqueue(db, user, JobKind.cv_parse, {})
    claim_next(db, now=old)
    assert requeue_stale(db) == 1
    db.refresh(j)
    assert j.status == JobStatus.queued and j.locked_at is None
    # fresh running job is left alone
    claim_next(db)
    assert requeue_stale(db) == 0
    # third attempt gives up
    j.status, j.attempts, j.locked_at = JobStatus.running, 3, old
    db.commit()
    requeue_stale(db)
    db.refresh(j)
    assert j.status == JobStatus.failed and j.last_error == "gave up after 3 attempts"


def _status(factory, job_id):
    with factory() as s:
        j = s.get(Job, job_id)
        return j.status, j.last_error, j.attempts


def test_success(db, user, factory):
    j = enqueue(db, user, JobKind.cv_parse, {})
    done = []
    assert run_once(
        factory, {JobKind.cv_parse: lambda d, job, llm: done.append(job.id)}, FakeLLM([])
    )
    assert done == [j.id] and _status(factory, j.id)[0] == JobStatus.done
    assert run_once(factory, {}, FakeLLM([])) is False


def test_transient_requeues_then_fails(db, user, factory):
    j = enqueue(db, user, JobKind.cv_parse, {})

    def boom(d, job, llm):
        raise LLMTransientError("busy")

    h = {JobKind.cv_parse: boom}
    for n in (1, 2):
        run_once(factory, h, FakeLLM([]))
        assert _status(factory, j.id)[::2] == (JobStatus.queued, n)
    run_once(factory, h, FakeLLM([]))
    status, err, attempts = _status(factory, j.id)
    assert (status, attempts) == (JobStatus.failed, 3) and err == "LLMTransientError: busy"


def test_permanent_fails_immediately_and_error_is_safe(db, user, factory):
    j = enqueue(db, user, JobKind.cv_parse, {})

    def boom(d, job, llm):
        raise RuntimeError("sk-ant-SECRET Jane Doe CV text")

    run_once(factory, {JobKind.cv_parse: boom}, FakeLLM([]))
    status, err, attempts = _status(factory, j.id)
    assert (status, attempts, err) == (JobStatus.failed, 1, "RuntimeError")


def test_llm_permanent_error_message_kept(db, user, factory):
    j = enqueue(db, user, JobKind.cv_parse, {})

    def boom(d, job, llm):
        raise LLMPermanentError("API status 400")

    run_once(factory, {JobKind.cv_parse: boom}, FakeLLM([]))
    assert _status(factory, j.id)[:2] == (JobStatus.failed, "LLMPermanentError: API status 400")


def test_missing_handler_fails(db, user, factory):
    j = enqueue(db, user, JobKind.repo_analyze, {})
    run_once(factory, {}, FakeLLM([]))
    assert _status(factory, j.id)[0] == JobStatus.failed


def test_handler_db_work_rolled_back_on_failure(db, user, factory):
    j = enqueue(db, user, JobKind.cv_parse, {})

    def boom(d, job, llm):
        job.payload = {"dirty": True}
        raise RuntimeError

    run_once(factory, {JobKind.cv_parse: boom}, FakeLLM([]))
    with factory() as s:
        assert s.scalar(select(Job.payload).where(Job.id == j.id)) == {}


def test_get_job_api(client, register, login, db):
    a = register("a@example.com")
    register("b@example.com")
    ha, hb = login("a@example.com"), login("b@example.com")
    job = enqueue(db, db.get(User, a["id"]), JobKind.cv_parse, {})
    r = client.get(f"/jobs/{job.id}", headers=ha)
    assert r.status_code == 200
    assert set(r.json()) == {"id", "kind", "status", "attempts", "last_error", "created_at"}
    assert r.json()["status"] == "queued"
    assert client.get(f"/jobs/{job.id}", headers=hb).status_code == 404
    assert client.get(f"/jobs/{job.id}").status_code == 401
    assert client.get("/jobs/nope", headers=ha).status_code == 404


def test_owner_deleted_mid_run_does_not_crash(db, user, factory):
    j = enqueue(db, user, JobKind.cv_parse, {})

    def delete_owner(d, job, llm):
        # Simulates DELETE /me committing from the API process while the job runs.
        with factory() as other:
            other.delete(other.get(User, job.user_id))
            other.commit()

    assert run_once(factory, {JobKind.cv_parse: delete_owner}, FakeLLM([])) is True
    with factory() as s:
        assert s.get(Job, j.id) is None


def test_worker_survives_iteration_error(monkeypatch, factory):
    import firstdev.jobs as jobs

    calls = {"n": 0}

    def flaky(*a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("database is locked")
        jobs_stop()
        return True

    def jobs_stop():
        import signal

        signal.raise_signal(signal.SIGTERM)

    monkeypatch.setattr(jobs, "run_once", flaky)
    monkeypatch.setattr(jobs, "requeue_stale", lambda db: 0)
    monkeypatch.setattr(jobs.time, "sleep", lambda s: None)
    jobs.worker_main(factory, FakeLLM([]), handlers={})
    assert calls["n"] == 2


@pytest.mark.backoff
def test_transient_failure_backs_off(db, user, factory):
    from firstdev.errors import TransientError

    j = enqueue(db, user, JobKind.cv_parse, {})

    def boom(d, job, llm):
        raise LLMTransientError("busy")

    before = datetime.now(UTC)
    run_once(factory, {JobKind.cv_parse: boom}, FakeLLM([]))
    with factory() as s:
        job = s.get(Job, j.id)
        assert job.status == JobStatus.queued
        assert job.run_after >= before + timedelta(seconds=30)
    # Not claimable until run_after passes, then claimable.
    with factory() as s:
        assert claim_next(s) is None
    with factory() as s:
        assert claim_next(s, now=datetime.now(UTC) + timedelta(seconds=31)).id == j.id

    from firstdev.jobs import retry_delay

    assert retry_delay(TransientError(), 1) == 30
    assert retry_delay(TransientError(), 2) == 60
    assert retry_delay(TransientError(retry_after=900), 1) == 900  # honour the service's reset
    assert retry_delay(TransientError(retry_after=10**6), 1) == 3600  # capped at 1h


def test_github_rate_limit_carries_retry_after():
    import respx

    from firstdev.github import GitHubClient, GitHubTransientError

    with respx.mock(base_url="https://api.github.com") as m:
        m.get("/repos/o/r").respond(
            403, headers={"x-ratelimit-remaining": "0", "retry-after": "120"}
        )
        with pytest.raises(GitHubTransientError) as e:
            GitHubClient().repo("o", "r")
    assert e.value.retry_after == 120
