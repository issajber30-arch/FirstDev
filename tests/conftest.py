# Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform.
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Set before any firstdev import so Settings never depends on the developer's .env.
os.environ["FIRSTDEV_JWT_SECRET"] = "test-secret-" + "x" * 40
os.environ["FIRSTDEV_ENV"] = "dev"

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
    def _register(email="dev@example.com", role="developer", password=PASSWORD):
        r = client.post("/auth/register", json={"email": email, "password": password, "role": role})
        assert r.status_code == 201, r.text
        return r.json()

    return _register


@pytest.fixture
def login(client):
    def _login(email="dev@example.com", password=PASSWORD):
        r = client.post("/auth/login", json={"email": email, "password": password})
        assert r.status_code == 200, r.text
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
