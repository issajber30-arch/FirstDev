# Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform.
from fastapi.testclient import TestClient

from firstdev.app import create_app
from firstdev.config import get_settings


def test_health_ok():
    r = TestClient(create_app()).get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_docs_disabled_in_prod(monkeypatch):
    monkeypatch.setenv("FIRSTDEV_ENV", "prod")
    monkeypatch.setenv("FIRSTDEV_PROXY_SECRET", "p" * 32)  # prod requires it
    monkeypatch.setenv("FIRSTDEV_COOKIE_SECURE", "true")
    get_settings.cache_clear()
    try:
        client = TestClient(create_app())
        assert client.get("/docs").status_code == 404
        assert client.get("/openapi.json").status_code == 404
    finally:
        get_settings.cache_clear()
