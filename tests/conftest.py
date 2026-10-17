# Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform.
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Set before any firstdev import so Settings never depends on the developer's .env.
os.environ["FIRSTDEV_JWT_SECRET"] = "test-secret-" + "x" * 40
os.environ["FIRSTDEV_ENV"] = "dev"
os.environ["FIRSTDEV_REQUIRE_INVITE"] = "false"  # invite tests turn it back on
os.environ["FIRSTDEV_COOKIE_SECURE"] = "false"  # TestClient speaks plain http

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from firstdev import auth  # noqa: E402
from firstdev.app import create_app  # noqa: E402
from firstdev.db import get_db, make_engine  # noqa: E402
from firstdev.models import Base  # noqa: E402


@pytest.fixture
def engine(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def db(engine):
    with sessionmaker(engine, expire_on_commit=False)() as session:
        yield session


@pytest.fixture
def client(engine):
    auth.login_limiter.reset()
    from firstdev.api import cv

    cv.rejected_uploads.reset()
    factory = sessionmaker(engine, expire_on_commit=False)

    def override():
        with factory() as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_db] = override
    return TestClient(app)


PASSWORD = "correct horse battery"


@pytest.fixture
def register(client):
    def _register(email="dev@example.com", role="developer", password=PASSWORD, **extra):
        body = {
            "email": email,
            "password": password,
            "role": role,
            "display_name": email.split("@")[0],
            **extra,
        }
        r = client.post("/auth/register", json=body)
        assert r.status_code == 201, r.text
        return r.json()

    return _register


@pytest.fixture
def set_env(monkeypatch):
    """Override FIRSTDEV_* settings for one test (Settings is cached, so clear it both ways)."""
    from firstdev.config import get_settings

    def _set(**kw):
        for k, v in kw.items():
            monkeypatch.setenv(f"FIRSTDEV_{k.upper()}", str(v))
        get_settings.cache_clear()

    yield _set
    monkeypatch.undo()
    get_settings.cache_clear()


@pytest.fixture
def login(client):
    def _login(email="dev@example.com", password=PASSWORD):
        r = client.post("/auth/login", json={"email": email, "password": password})
        assert r.status_code == 200, r.text
        client.cookies.clear()  # keep existing tests Bearer-only: no ambient cookie session
        return {"Authorization": f"Bearer {r.json()['access_token']}"}

    return _login


@pytest.fixture
def dev_headers(register, login):
    register()
    return login()


@pytest.fixture(autouse=True)
def _no_retry_backoff(request, monkeypatch):
    # Retried jobs are claimable immediately in tests unless a test checks backoff itself.
    if "backoff" not in request.keywords:
        from firstdev import jobs

        monkeypatch.setattr(jobs, "retry_delay", lambda exc, attempts: 0)


@pytest.fixture
def user_factory(db):
    from firstdev.models import DeveloperProfile, Role, User

    def _make(email="u@example.com", role=Role.developer):
        u = User(email=email, password_hash="h", role=role)
        db.add(u)
        db.flush()
        if role == Role.developer:
            db.add(DeveloperProfile(user_id=u.id))
        db.commit()
        return u

    return _make


@pytest.fixture
def profile(db, user_factory):
    from firstdev.models import DeveloperProfile

    return db.get(DeveloperProfile, user_factory("dev@example.com").id)


@pytest.fixture
def posting(db, user_factory):
    from firstdev.models import JobPosting, PostingStatus, Role

    rec = user_factory("rec@example.com", Role.recruiter)
    p = JobPosting(recruiter_id=rec.id, title="t", description="d", status=PostingStatus.open)
    db.add(p)
    db.commit()
    return p


@pytest.fixture(autouse=True)
def fake_embedder(monkeypatch):
    """No test may build a FastEmbedder or download a model: get_embedder returns a fake."""
    from firstdev.matching import embeddings

    fake = embeddings.FakeEmbedder()
    monkeypatch.setattr(embeddings, "get_embedder", lambda: fake)
    return fake
