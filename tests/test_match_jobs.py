# Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform.
import pytest
from conftest import PASSWORD
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from firstdev.jobs import HANDLERS, enqueue, enqueue_embed_profile, run_once
from firstdev.llm import FakeLLM
from firstdev.matching import embeddings
from firstdev.matching.embeddings import EmbeddingUnavailable
from firstdev.matching.vectors import from_blob
from firstdev.models import (
    CvDocument,
    CvParse,
    CvStatus,
    Embedding,
    Job,
    JobKind,
    JobStatus,
    OwnerKind,
    User,
)
from firstdev.pipelines import match_jobs  # noqa: F401  (registers handlers)


@pytest.fixture
def factory(engine):
    return sessionmaker(engine, expire_on_commit=False)


def run(factory):
    return run_once(factory, HANDLERS, FakeLLM([]))


def add_cv(db, profile, skills):
    doc = CvDocument(profile_id=profile.user_id, sha256="h", size=1, status=CvStatus.parsed)
    db.add(doc)
    db.flush()
    data = {"skills": [{"name": n, "years": None} for n in skills], "experience": []}
    db.add(CvParse(cv_document_id=doc.id, schema_version=1, model="m", data=data))
    db.commit()


def embeds(db):
    db.expire_all()
    return db.scalars(select(Embedding)).all()


def test_handlers_registered():
    assert JobKind.embed_profile in HANDLERS and JobKind.embed_posting in HANDLERS


def test_embed_profile_stores_vector(db, factory, profile, fake_embedder):
    profile.headline = "Dev"
    add_cv(db, profile, ["Python"])
    user = db.get(User, profile.user_id)
    enqueue(db, user, JobKind.embed_profile, {"profile_id": profile.user_id})
    assert run(factory)
    (e,) = embeds(db)
    assert (e.owner_kind, e.profile_id, e.model, e.dim) == (
        OwnerKind.profile,
        profile.user_id,
        fake_embedder.model,
        fake_embedder.dim,
    )
    assert len(from_blob(e.vector, e.dim)) == fake_embedder.dim
    assert db.scalars(select(Job)).one().status == JobStatus.done


def test_unchanged_fingerprint_skips_reembedding(db, factory, profile, fake_embedder):
    add_cv(db, profile, ["Python"])
    user = db.get(User, profile.user_id)
    for _ in range(2):
        enqueue(db, user, JobKind.embed_profile, {"profile_id": profile.user_id})
        assert run(factory)
    assert fake_embedder.calls == 1 and len(embeds(db)) == 1
    add_cv(db, profile, ["Python", "Go"])  # CV changed
    enqueue(db, user, JobKind.embed_profile, {"profile_id": profile.user_id})
    assert run(factory)
    assert fake_embedder.calls == 2 and len(embeds(db)) == 1


def test_deleted_profile_is_noop(db, factory, profile, fake_embedder):
    user = db.get(User, profile.user_id)
    enqueue(db, user, JobKind.embed_profile, {"profile_id": "gone"})
    enqueue(db, user, JobKind.embed_profile, {})
    assert run(factory) and run(factory)
    assert fake_embedder.calls == 0 and embeds(db) == []
    assert {j.status for j in db.scalars(select(Job))} == {JobStatus.done}


def test_embed_posting(db, factory, posting, fake_embedder):
    rec = db.get(User, posting.recruiter_id)
    enqueue(db, rec, JobKind.embed_posting, {"posting_id": posting.id})
    enqueue(db, rec, JobKind.embed_posting, {"posting_id": posting.id})
    assert run(factory) and run(factory)
    (e,) = embeds(db)
    assert (e.owner_kind, e.posting_id) == (OwnerKind.posting, posting.id)
    assert fake_embedder.calls == 1  # second run: same fingerprint
    posting.title = "Different title"
    db.commit()
    enqueue(db, rec, JobKind.embed_posting, {"posting_id": posting.id})
    assert run(factory)
    assert fake_embedder.calls == 2 and len(embeds(db)) == 1


def test_deleted_posting_is_noop(db, factory, user_factory, fake_embedder):
    rec = user_factory("r@example.com", role="recruiter")
    enqueue(db, rec, JobKind.embed_posting, {"posting_id": "gone"})
    assert run(factory) and fake_embedder.calls == 0


def test_model_unavailable_retries_then_fails(db, factory, profile, monkeypatch):
    class Down:
        model, dim = "m", 4

        def embed(self, texts):
            raise EmbeddingUnavailable("model download failed")

    monkeypatch.setattr(embeddings, "get_embedder", lambda: Down())
    user = db.get(User, profile.user_id)
    job = enqueue(db, user, JobKind.embed_profile, {"profile_id": profile.user_id})
    for expected in (JobStatus.queued, JobStatus.queued, JobStatus.failed):
        assert run(factory)
        db.expire_all()
        assert db.get(Job, job.id).status == expected
    assert db.get(Job, job.id).last_error == "EmbeddingUnavailable"


def test_enqueue_embed_profile_dedupes_and_uses_owner(db, profile):
    j = enqueue_embed_profile(db, profile.user_id)
    assert (j.user_id, j.payload, j.kind) == (
        profile.user_id,
        {"profile_id": profile.user_id},
        JobKind.embed_profile,
    )
    assert enqueue_embed_profile(db, profile.user_id) is None
    assert enqueue_embed_profile(db, "missing") is None
    assert db.query(Job).count() == 1
    j.status = JobStatus.done  # once it has run, a new one may be queued
    db.commit()
    assert enqueue_embed_profile(db, profile.user_id) is not None


def test_delete_me_removes_embeddings(client, dev_headers, db, factory):
    user = db.scalars(select(User)).one()
    enqueue(db, user, JobKind.embed_profile, {"profile_id": user.id})
    assert run(factory) and len(embeds(db)) == 1
    r = client.request("DELETE", "/me", headers=dev_headers, json={"password": PASSWORD})
    assert r.status_code == 204
    assert embeds(db) == []


# --- score_pair ----------------------------------------------------------------------------------
import logging  # noqa: E402

from firstdev.llm import LLMRefused, LLMTransientError  # noqa: E402
from firstdev.matching.explain import Equivalence, Feedback, MatchReview  # noqa: E402
from firstdev.matching.profile import build_skill_profile  # noqa: E402
from firstdev.models import Application, MatchScore  # noqa: E402
from firstdev.pipelines.match_jobs import is_stale  # noqa: E402


def review(adj=0, reason=""):
    return MatchReview(
        equivalences=[], adjustment=adj, adjustment_reason=reason, reasons=["fits"],
        feedback=Feedback(strengths=["py"], missing_skills=[], suggestions=[]),
    )  # fmt: skip


@pytest.fixture
def scored_setup(db, profile, posting):
    posting.required_skills = ["python"]
    posting.optional_skills = ["docker"]
    posting.description = "SECRET-POSTING-TEXT"
    add_cv(db, profile, ["Python"])
    app = Application(job_posting_id=posting.id, profile_id=profile.user_id)
    db.add(app)
    db.commit()
    return posting, profile, app


def enqueue_score(db, profile, posting, app=None, explain=True):
    payload = {"posting_id": posting.id, "profile_id": profile.user_id, "explain": explain}
    if app is not None:
        payload["application_id"] = app.id
    return enqueue(db, db.get(User, profile.user_id), JobKind.score_pair, payload)


def test_score_pair_apply_flow_and_cache(db, factory, scored_setup):
    posting, profile, app = scored_setup
    llm = FakeLLM([review(5, "evidence")])
    enqueue_score(db, profile, posting, app)
    assert run_once(factory, HANDLERS, llm)
    db.expire_all()
    ms = db.scalars(select(MatchScore)).one()
    assert ms.explained and ms.llm_adjustment == 5 and ms.model == "fake-model"
    assert ms.score == round(ms.base_score + 5) and ms.reasons == ["fits"]
    assert db.get(Application, app.id).match_score_id == ms.id
    # Second run, nothing changed: the LLM queue is empty, so any call would raise.
    enqueue_score(db, profile, posting, app)
    assert run_once(factory, HANDLERS, llm)
    assert len(llm.calls) == 1
    assert {j.status for j in db.scalars(select(Job))} == {JobStatus.done}


def test_posting_edit_makes_score_stale_and_rescored(db, factory, scored_setup):
    posting, profile, app = scored_setup
    llm = FakeLLM([review(), review(3, "new evidence")])
    enqueue_score(db, profile, posting, app)
    assert run_once(factory, HANDLERS, llm)
    db.expire_all()
    ms = db.scalars(select(MatchScore)).one()
    old_fp = ms.posting_fingerprint
    assert not is_stale(ms, posting, build_skill_profile(db, profile))
    posting.required_skills = ["python", "go"]
    db.commit()
    assert is_stale(ms, posting, build_skill_profile(db, profile))
    enqueue_score(db, profile, posting, app)
    assert run_once(factory, HANDLERS, llm)
    db.expire_all()
    ms = db.scalars(select(MatchScore)).one()
    assert len(llm.calls) == 2 and ms.posting_fingerprint != old_fp and ms.llm_adjustment == 3
    assert not is_stale(ms, posting, build_skill_profile(db, profile))


def test_profile_change_makes_score_stale(db, factory, scored_setup):
    posting, profile, _ = scored_setup
    enqueue_score(db, profile, posting, explain=False)
    assert run_once(factory, HANDLERS, FakeLLM([]))
    ms = db.scalars(select(MatchScore)).one()
    assert not ms.explained and ms.model == "formula" and ms.llm_adjustment == 0
    add_cv(db, profile, ["Python", "Docker"])
    assert is_stale(ms, posting, build_skill_profile(db, profile))


def test_explain_upgrades_unexplained_score(db, factory, scored_setup):
    posting, profile, _ = scored_setup
    enqueue_score(db, profile, posting, explain=False)
    assert run_once(factory, HANDLERS, FakeLLM([]))
    llm = FakeLLM([review()])
    enqueue_score(db, profile, posting, explain=True)
    assert run_once(factory, HANDLERS, llm) and len(llm.calls) == 1
    db.expire_all()
    assert db.scalars(select(MatchScore)).one().explained


def test_scored_without_embedding(db, factory, scored_setup):
    posting, profile, app = scored_setup
    assert embeds(db) == []
    enqueue_score(db, profile, posting, app, explain=False)
    assert run_once(factory, HANDLERS, FakeLLM([]))
    db.expire_all()
    assert db.scalars(select(MatchScore)).one().score > 0
    assert db.scalars(select(Job)).one().status == JobStatus.done


def test_equivalence_recomputes_base_and_components(db, factory, scored_setup):
    posting, profile, _ = scored_setup
    posting.required_skills = ["python", "postgresql"]
    db.commit()
    add_cv(db, profile, ["Python", "Postgres SQL"])
    r = review(2, "x")
    r.equivalences = [Equivalence(posting_skill="postgresql", candidate_skill="postgres sql")]
    enqueue_score(db, profile, posting)
    assert run_once(factory, HANDLERS, FakeLLM([r]))
    db.expire_all()
    ms = db.scalars(select(MatchScore)).one()
    assert ms.components["required_cov"] == 0.6  # both cv-level: (0.6 + 0.6) / 2


def test_missing_posting_profile_or_application_no_crash(db, factory, scored_setup):
    posting, profile, app = scored_setup
    user = db.get(User, profile.user_id)
    enqueue(db, user, JobKind.score_pair, {"posting_id": "gone", "profile_id": profile.user_id})
    enqueue(db, user, JobKind.score_pair, {"posting_id": posting.id, "profile_id": "gone"})
    enqueue(db, user, JobKind.score_pair, {})
    ghost_app = {"posting_id": posting.id, "profile_id": profile.user_id, "application_id": "gone"}
    enqueue(db, user, JobKind.score_pair, ghost_app)
    for _ in range(4):
        assert run_once(factory, HANDLERS, FakeLLM([]))
    assert {j.status for j in db.scalars(select(Job))} == {JobStatus.done}
    assert len(db.scalars(select(MatchScore)).all()) == 1  # only the last (explain false) scored


def test_foreign_application_not_linked(db, factory, scored_setup, user_factory):
    posting, profile, _ = scored_setup
    other = user_factory("other@example.com")
    foreign = Application(job_posting_id=posting.id, profile_id=other.id)
    db.add(foreign)
    db.commit()
    enqueue_score(db, profile, posting, foreign, explain=False)
    assert run_once(factory, HANDLERS, FakeLLM([]))
    db.expire_all()
    assert db.get(Application, foreign.id).match_score_id is None


def test_transient_llm_error_requeues_without_score(db, factory, scored_setup):
    posting, profile, _ = scored_setup
    job = enqueue_score(db, profile, posting)
    assert run_once(factory, HANDLERS, FakeLLM([LLMTransientError("RateLimitError")]))
    db.expire_all()
    assert db.get(Job, job.id).status == JobStatus.queued
    assert db.scalars(select(MatchScore)).all() == []


def test_refusal_fails_job_and_stores_no_score(db, factory, scored_setup):
    posting, profile, app = scored_setup
    job = enqueue_score(db, profile, posting, app)
    assert run_once(factory, HANDLERS, FakeLLM([LLMRefused("x")]))
    db.expire_all()
    assert db.get(Job, job.id).status == JobStatus.failed
    assert db.scalars(select(MatchScore)).all() == []
    assert db.get(Application, app.id).match_score_id is None


def test_refusal_on_rescore_keeps_old_score(db, factory, scored_setup):
    posting, profile, app = scored_setup
    enqueue_score(db, profile, posting, app)
    assert run_once(factory, HANDLERS, FakeLLM([review(4, "e")]))
    posting.required_skills = ["go"]
    db.commit()
    enqueue_score(db, profile, posting, app)
    assert run_once(factory, HANDLERS, FakeLLM([LLMRefused("x")]))
    db.expire_all()
    ms = db.scalars(select(MatchScore)).one()
    assert ms.llm_adjustment == 4 and ms.components["required"][0]["skill"] == "python"


def test_logs_have_no_posting_text(db, factory, scored_setup, caplog):
    posting, profile, app = scored_setup
    enqueue_score(db, profile, posting, app)
    with caplog.at_level(logging.DEBUG):
        assert run_once(factory, HANDLERS, FakeLLM([review()]))
    assert "scored posting=" in caplog.text
    assert "SECRET-POSTING-TEXT" not in caplog.text
