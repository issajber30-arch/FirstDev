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
