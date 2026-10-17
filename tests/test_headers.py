# Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform.
import pytest
from starlette.requests import Request

from firstdev import auth
from firstdev.config import Settings

SECRET = "proxy-secret-" + "s" * 20


def _req(headers: dict[str, str], host: str = "10.0.0.9") -> Request:
    raw = [(k.lower().encode(), v.encode()) for k, v in headers.items()]
    return Request({"type": "http", "headers": raw, "client": (host, 1234), "method": "GET"})


def test_spoofed_client_ip_ignored_without_secret(set_env):
    set_env(proxy_secret=SECRET)
    assert auth.client_ip(_req({"X-FirstDev-Client-IP": "1.2.3.4"})) == "10.0.0.9"
    wrong = {"X-FirstDev-Client-IP": "1.2.3.4", "X-FirstDev-Proxy-Secret": "nope"}
    assert auth.client_ip(_req(wrong)) == "10.0.0.9"


def test_client_ip_honoured_with_secret(set_env):
    set_env(proxy_secret=SECRET)
    h = {"X-FirstDev-Client-IP": "1.2.3.4", "X-FirstDev-Proxy-Secret": SECRET}
    assert auth.client_ip(_req(h)) == "1.2.3.4"
    # secret matches but no IP header -> fall back to the socket peer
    assert auth.client_ip(_req({"X-FirstDev-Proxy-Secret": SECRET})) == "10.0.0.9"


def test_client_ip_without_configured_secret_never_trusts_header(set_env):
    h = {"X-FirstDev-Client-IP": "1.2.3.4", "X-FirstDev-Proxy-Secret": ""}
    assert auth.client_ip(_req(h)) == "10.0.0.9"


def test_limiter_keys_use_client_ip(set_env):
    set_env(proxy_secret=SECRET)
    h = {"X-FirstDev-Client-IP": "1.2.3.4", "X-FirstDev-Proxy-Secret": SECRET}
    assert auth.limiter_keys(_req(h), "a@b.co") == ("ip:1.2.3.4", "email:a@b.co")


def test_security_headers_on_every_response(client):
    for r in (client.get("/health"), client.get("/me"), client.get("/nope")):
        assert r.headers["x-content-type-options"] == "nosniff"
        assert r.headers["referrer-policy"] == "no-referrer"
        assert r.headers["x-frame-options"] == "DENY"
        assert r.headers["content-security-policy"] == "default-src 'none'; frame-ancestors 'none'"
        assert "strict-transport-security" not in r.headers  # dev


def test_headers_on_middleware_rejections(client, register):
    register()
    client.post(
        "/auth/login", json={"email": "dev@example.com", "password": "correct horse battery"}
    )
    r = client.post("/profiles/me")  # cookie-authenticated, no CSRF header
    assert r.status_code == 403 and r.headers["x-frame-options"] == "DENY"


def test_hsts_only_in_prod(client, set_env):
    set_env(env="prod", proxy_secret=SECRET, cookie_secure="true", turnstile_disabled="false")
    r = client.get("/health")
    assert r.headers["strict-transport-security"] == "max-age=31536000"


def test_no_store_when_request_carries_credentials(client):
    assert "cache-control" not in client.get("/health").headers
    assert (
        client.get("/health", headers={"Authorization": "Bearer x"}).headers["cache-control"]
        == "no-store"
    )
    assert (
        client.get("/health", headers={"Cookie": "fd_access=x"}).headers["cache-control"]
        == "no-store"
    )


def test_no_store_on_auth_responses(client, register):
    register()
    r = client.post(
        "/auth/login", json={"email": "dev@example.com", "password": "correct horse battery"}
    )
    assert r.headers["cache-control"] == "no-store"


def test_prod_requires_proxy_secret_and_secure_cookies(monkeypatch):
    base = {"jwt_secret": "j" * 40, "env": "prod", "turnstile_disabled": False}
    with pytest.raises(ValueError, match="PROXY_SECRET"):
        Settings(_env_file=None, cookie_secure=True, **base)
    with pytest.raises(ValueError, match="COOKIE_SECURE"):
        Settings(_env_file=None, proxy_secret=SECRET, cookie_secure=False, **base)
    with pytest.raises(ValueError, match="PROXY_SECRET"):
        Settings(_env_file=None, proxy_secret="", cookie_secure=True, **base)
    ok = Settings(_env_file=None, proxy_secret=SECRET, cookie_secure=True, **base)
    assert ok.env == "prod"
    # dev stays permissive
    Settings(_env_file=None, jwt_secret="j" * 40, env="dev", cookie_secure=False)
