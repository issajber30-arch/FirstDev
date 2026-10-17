# Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform.
import threading
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import anthropic
import httpx2 as httpx
import pytest
from assess_helpers import seed
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker
from test_repo_analyzer import FakeGitHub

from firstdev import budget
from firstdev.budget import BudgetExceeded
from firstdev.jobs import HANDLERS, enqueue, run_once
from firstdev.llm import (
    AnthropicLLM,
    FakeLLM,
    LLMContext,
    LLMPermanentError,
    LLMRefused,
    LLMTransientError,
)
from firstdev.models import (
    AssessmentAnswer,
    AssessmentQuestion,
    AssessmentStatus,
    CvDocument,
    Job,
    JobKind,
    JobStatus,
    LedgerStatus,
    LlmLedger,
    QuestionKind,
    Repository,
)
from firstdev.pipelines import repo_analyzer

CTX = LLMContext(None, None, "cv_parse")


class Out(BaseModel):
    name: str


@pytest.fixture
def factory(engine):
    return sessionmaker(engine, expire_on_commit=False)


@pytest.fixture(autouse=True)
def cap(set_env):
    set_env(llm_daily_usd=5.0)


def rows(factory):
    with factory() as s:
        return list(s.scalars(select(LlmLedger).order_by(LlmLedger.created_at)))


def add_row(factory, *, reserved, actual=None, status=LedgerStatus.reserved, day=None):
    with factory() as s:
        s.add(
            LlmLedger(
                day=day or datetime.now(UTC).date(),
                kind="x",
                reserved_usd=reserved,
                actual_usd=actual,
                status=status,
            )
        )
        s.commit()


def client_for(*, parsed=None, raises=None, stop_reason="end_turn", usage=(1000, 500)):
    calls = []

    def parse(**kw):
        calls.append(kw)
        if raises:
            raise raises
        return SimpleNamespace(
            model="claude-opus-5-5",
            _request_id="r",
            stop_reason=stop_reason,
            stop_details=SimpleNamespace(category=None),
            parsed_output=parsed,
            usage=SimpleNamespace(input_tokens=usage[0], output_tokens=usage[1]),
        )

    return SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(parse=parse))), calls


# --- reserve / settle / release ----------------------------------------------------------------


def test_reserve_settle_release(factory, user_factory):
    u = user_factory()
    rid = budget.reserve(factory, LLMContext(u.id, "w1", "cv_parse"), 1.25)
    (r,) = rows(factory)
    assert (r.id, r.user_id, r.world_id, r.kind) == (rid, u.id, "w1", "cv_parse")
    assert (r.reserved_usd, r.actual_usd, r.status) == (1.25, None, LedgerStatus.reserved)
    assert r.day == datetime.now(UTC).date()
    budget.settle(factory, rid, SimpleNamespace(model="claude-opus-5-5", input_tokens=1000,
                                                output_tokens=500))  # fmt: skip
    (r,) = rows(factory)
    assert r.status == LedgerStatus.settled and r.actual_usd == pytest.approx(0.014)
    rid2 = budget.reserve(factory, CTX, 1.0)
    budget.release(factory, rid2)
    assert [x.status for x in rows(factory)] == [LedgerStatus.settled, LedgerStatus.released]


def test_total_uses_actual_when_settled_else_reserved(factory):
    add_row(factory, reserved=3.0, actual=1.0, status=LedgerStatus.settled)
    add_row(factory, reserved=0.5)
    add_row(factory, reserved=4.0, status=LedgerStatus.released)  # not counted
    budget.reserve(factory, CTX, 3.5)  # 1.5 + 3.5 == cap exactly: allowed
    with pytest.raises(BudgetExceeded):
        budget.reserve(factory, CTX, 0.01)


def test_day_rollover_resets_total(factory):
    now = datetime.now(UTC)
    budget.reserve(factory, CTX, 5.0, now=now - timedelta(days=1))
    with pytest.raises(BudgetExceeded):
        budget.reserve(factory, CTX, 0.1, now=now - timedelta(days=1))
    budget.reserve(factory, CTX, 5.0, now=now)  # a new UTC day starts from zero


def test_refused_reservation_inserts_nothing(factory):
    with pytest.raises(BudgetExceeded):
        budget.reserve(factory, CTX, 5.01)
    assert rows(factory) == []


def test_budget_exceeded_is_permanent_with_safe_message():
    e = BudgetExceeded()
    assert isinstance(e, LLMPermanentError) and not isinstance(e, LLMTransientError)
    assert str(e) == "demo AI budget reached for today"


def test_estimate_worst_case():
    # (len//3 + 1) input tokens at $4/MTok plus max_tokens at $20/MTok
    assert budget.estimate_worst_usd("a" * 300, "b" * 300, 1000) == pytest.approx(
        (201 * 4 + 1000 * 20) / 1_000_000
    )


def test_concurrent_reservations_never_exceed_cap(factory):
    results = []
    barrier = threading.Barrier(10)

    def worker():
        barrier.wait()
        try:
            budget.reserve(factory, CTX, 0.6)
            results.append(True)
        except BudgetExceeded:
            results.append(False)

    threads = [threading.Thread(target=worker) for _ in range(10)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sum(results) == 8 and len(results) == 10  # 8 * 0.6 = 4.8 <= 5 < 5.4
    assert len(rows(factory)) == 8


# --- AnthropicLLM integration ------------------------------------------------------------------


def test_extract_reserves_calls_then_settles(factory, user_factory):
    u = user_factory()
    client, calls = client_for(parsed=Out(name="x"))
    llm = AnthropicLLM(client, db_factory=factory)
    r = llm.extract(Out, "sys", "user", context=LLMContext(u.id, None, "repo_analyze"))
    assert r.data == Out(name="x") and len(calls) == 1
    (row,) = rows(factory)
    assert (row.status, row.kind, row.user_id) == (LedgerStatus.settled, "repo_analyze", u.id)
    assert row.actual_usd == pytest.approx((1000 * 4 + 500 * 20) / 1_000_000)
    assert row.reserved_usd > row.actual_usd


def test_no_context_still_reserves(factory):
    client, _ = client_for(parsed=Out(name="x"))
    AnthropicLLM(client, db_factory=factory).extract(Out, "s", "u")
    assert rows(factory)[0].kind == "unknown"


def _status_err(code):
    resp = httpx.Response(code, request=httpx.Request("POST", "https://api.anthropic.com/v1"))
    return anthropic.APIStatusError("x", response=resp, body=None)


@pytest.mark.parametrize(
    ("raises", "exc"),
    [
        (_status_err(500), LLMTransientError),
        (_status_err(400), LLMPermanentError),
        (RuntimeError("boom"), RuntimeError),
    ],
)
def test_failed_call_releases_reservation(factory, raises, exc):
    client, _ = client_for(raises=raises)
    with pytest.raises(exc):
        AnthropicLLM(client, db_factory=factory).extract(Out, "s", "u", context=CTX)
    (row,) = rows(factory)
    assert row.status == LedgerStatus.released


def test_billed_failures_stay_counted(factory):
    # A refusal was billed: settle at real usage. A schema mismatch has no usage: the
    # worst-case reservation stays counted rather than being released.
    client, _ = client_for(stop_reason="refusal")
    with pytest.raises(LLMRefused):
        AnthropicLLM(client, db_factory=factory).extract(Out, "s", "u", context=CTX)
    assert rows(factory)[0].status == LedgerStatus.settled

    def bad(**kw):
        Out.model_validate({})

    bad_client = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(parse=bad)))
    with pytest.raises(Exception, match="schema validation"):
        AnthropicLLM(bad_client, db_factory=factory).extract(Out, "s", "u", context=CTX)
    assert rows(factory)[1].status == LedgerStatus.reserved


def test_budget_refuses_before_any_client_call(factory):
    """Review Focus 3: near the cap, a big reservation never reaches the API."""
    add_row(factory, reserved=4.99, actual=4.99, status=LedgerStatus.settled)
    client, calls = client_for(parsed=Out(name="x"))
    with pytest.raises(BudgetExceeded):
        AnthropicLLM(client, db_factory=factory).extract(Out, "s", "u" * 100_000, context=CTX)
    assert calls == []
    assert len(rows(factory)) == 1  # nothing reserved, so nothing to release


def test_job_fails_immediately_with_budget_message(factory, profile, db):
    add_row(factory, reserved=4.999, actual=4.999, status=LedgerStatus.settled)
    doc = CvDocument(profile_id=profile.user_id, sha256="x", size=5, extracted_text="Python dev")
    db.add(doc)
    db.commit()
    job = enqueue(db, _user(db, profile), JobKind.cv_parse, {"cv_document_id": doc.id})
    client, calls = client_for(parsed=None)
    assert run_once(factory, HANDLERS, AnthropicLLM(client, db_factory=factory))
    db.expire_all()
    j = db.get(Job, job.id)
    assert j.status == JobStatus.failed and j.attempts == 1  # permanent: no retry
    assert j.last_error == "BudgetExceeded: demo AI budget reached for today"
    assert calls == []


def _user(db, profile):
    from firstdev.models import User

    return db.get(User, profile.user_id)


# --- context threading -------------------------------------------------------------------------


def test_fake_llm_records_context():
    fake = FakeLLM([Out(name="a")])
    fake.extract(Out, "s", "u", context=CTX)
    assert fake.contexts == [CTX]


def _run(factory, db, user, kind, payload, setup_llm=None):
    enqueue(db, user, kind, payload)
    llm = FakeLLM([LLMPermanentError("stop")])  # records the context, then fails the job
    assert run_once(factory, HANDLERS, llm)
    return llm


def test_every_pipeline_passes_context(factory, db, profile, posting, monkeypatch):
    user = _user(db, profile)
    expect = lambda kind: [LLMContext(user.id, None, kind)]  # noqa: E731

    doc = CvDocument(profile_id=profile.user_id, sha256="x", size=5, extracted_text="Python dev")
    db.add(doc)
    db.commit()
    llm = _run(factory, db, user, JobKind.cv_parse, {"cv_document_id": doc.id})
    assert llm.contexts == expect("cv_parse")

    repo = Repository(profile_id=profile.user_id, owner="octo", name="hello")
    db.add(repo)
    db.commit()
    monkeypatch.setattr(repo_analyzer, "get_github", lambda: FakeGitHub({"a.py": "x = 1"}))
    llm = _run(factory, db, user, JobKind.repo_analyze, {"repository_id": repo.id})
    assert llm.contexts == expect("repo_analyze")

    payload = {"posting_id": posting.id, "profile_id": profile.user_id, "explain": True}
    llm = _run(factory, db, user, JobKind.score_pair, payload)
    assert llm.contexts == expect("score_pair")

    gen = seed(db, profile, status=AssessmentStatus.generating)
    llm = _run(factory, db, user, JobKind.assessment_generate, {"assessment_id": gen.id})
    assert llm.contexts == expect("assessment_generate")

    sub = seed(db, profile, status=AssessmentStatus.submitted)
    for q in db.scalars(
        select(AssessmentQuestion).where(
            AssessmentQuestion.assessment_id == sub.id,
            AssessmentQuestion.kind == QuestionKind.short,
        )
    ):
        db.add(AssessmentAnswer(question_id=q.id, text="an answer"))
    db.commit()
    llm = _run(factory, db, user, JobKind.assessment_grade, {"assessment_id": sub.id})
    assert llm.contexts == expect("assessment_grade")


def test_no_ledger_rows_from_fakes(factory, db, profile):
    assert db.scalar(select(func.count()).select_from(LlmLedger)) == 0
