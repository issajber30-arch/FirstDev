# Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform.
import hashlib
from datetime import UTC, datetime, timedelta

from conftest import PASSWORD
from sqlalchemy import select

from firstdev.models import RefreshToken, User


def _login(client, email="dev@example.com"):
    r = client.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert r.status_code == 200, r.text
    return r


def _cookie_headers(resp):
    return {h.split("=", 1)[0]: h for h in resp.headers.get_list("set-cookie")}


def _refresh(client, raw):
    # The refresh cookie is Path=/api/auth (the Next.js proxy prefix), so the jar never sends
    # it to /auth/refresh in tests; present it explicitly.
    return client.post("/auth/refresh", headers={"Cookie": f"fd_refresh={raw}"})


def _session(client, register):
    register()
    r = _login(client)
    return r, client.cookies.get("fd_csrf")


def _raw_refresh(resp):
    return _cookie_headers(resp)["fd_refresh"].split(";")[0].split("=", 1)[1]


def test_login_sets_cookies_with_flags_and_still_returns_token(client, register):
    register()
    r = _login(client)
    assert r.json()["token_type"] == "bearer" and r.json()["access_token"]
    c = _cookie_headers(r)
    assert set(c) == {"fd_access", "fd_refresh", "fd_csrf"}
    acc, ref, csrf = (c[k].lower() for k in ("fd_access", "fd_refresh", "fd_csrf"))
    assert "httponly" in acc and "samesite=lax" in acc and "path=/;" in acc + ";"
    assert "max-age=900" in acc
    assert "httponly" in ref and "samesite=strict" in ref and "path=/auth" in ref
    assert "max-age=604800" in ref
    assert "httponly" not in csrf and "samesite=strict" in csrf and "path=/" in csrf
    assert all("secure" not in x for x in (acc, ref, csrf))  # conftest: cookie_secure=false


def test_secure_flag_follows_setting(client, register, set_env):
    register()
    set_env(cookie_secure="true")
    r = client.post("/auth/login", json={"email": "dev@example.com", "password": PASSWORD})
    assert all("; secure" in h.lower() for h in r.headers.get_list("set-cookie"))


def test_me_with_cookie_only(client, register):
    register()
    _login(client)
    r = client.get("/me")  # jar sends fd_access, no Authorization header
    assert r.status_code == 200 and r.json()["email"] == "dev@example.com"


def test_bearer_wins_over_cookie(client, register):
    register()
    _login(client)
    r = client.get("/me", headers={"Authorization": "Bearer garbage"})
    assert r.status_code == 401


def test_csrf_required_for_cookie_unsafe_methods(client, register):
    register()
    _login(client)
    csrf = client.cookies.get("fd_csrf")
    body = {"headline": "hi"}
    assert client.put("/profiles/me", json=body).status_code == 403
    r = client.put("/profiles/me", json=body, headers={"X-CSRF-Token": "wrong"})
    assert r.status_code == 403 and r.json() == {"detail": "CSRF token missing or invalid"}
    assert client.put("/profiles/me", json=body, headers={"X-CSRF-Token": ""}).status_code == 403
    r = client.put("/profiles/me", json=body, headers={"X-CSRF-Token": csrf})
    assert r.status_code == 200, r.text
    # safe methods need no token
    assert client.get("/me").status_code == 200


def test_csrf_missing_csrf_cookie_is_403(client, register):
    register()
    _login(client)
    client.cookies.delete("fd_csrf")
    r = client.put("/profiles/me", json={"headline": "x"}, headers={"X-CSRF-Token": "anything"})
    assert r.status_code == 403


def test_bearer_exempt_from_csrf(client, register, login):
    register()
    h = login()
    client.cookies.clear()
    assert client.put("/profiles/me", json={"headline": "x"}, headers=h).status_code == 200
    # Bearer plus a stray cookie is still Bearer-authenticated.
    client.cookies.set("fd_access", "junk")
    assert client.put("/profiles/me", json={"headline": "y"}, headers=h).status_code == 200


def test_csrf_exempt_paths(client, register):
    register()
    _login(client)  # cookies now present; login itself must not need a token
    r = client.post("/auth/login", json={"email": "dev@example.com", "password": PASSWORD})
    assert r.status_code == 200
    assert client.post("/auth/register", json={}).status_code == 422  # reaches the route
    assert client.post("/auth/refresh").status_code == 204  # reaches the route without a CSRF token
    assert client.post("/auth/logout").status_code == 403  # logout is not exempt


def test_refresh_rotates(client, register, db):
    register()
    login = _login(client)
    old = _raw_refresh(login)
    r = _refresh(client, old)
    assert r.status_code == 204
    c = _cookie_headers(r)
    assert set(c) == {"fd_access", "fd_refresh", "fd_csrf"}
    new = _raw_refresh(r)
    assert new != old
    rows = db.scalars(select(RefreshToken).order_by(RefreshToken.created_at)).all()
    assert len(rows) == 2 and rows[0].family_id == rows[1].family_id
    assert rows[0].used_at is not None and rows[1].used_at is None
    assert (rows[1].expires_at - datetime.now(UTC)) > timedelta(days=6, hours=23)
    assert _refresh(client, new).status_code == 204


def test_refresh_reuse_revokes_family(client, register, db):
    register()
    old = _raw_refresh(_login(client))
    new = _raw_refresh(_refresh(client, old))
    assert _refresh(client, old).status_code == 401  # reuse
    assert _refresh(client, new).status_code == 401  # sibling is dead too
    assert all(t.revoked_at is not None for t in db.scalars(select(RefreshToken)))


def test_two_sequential_refreshes_same_token(client, register, db):
    # Review Focus 2: the second concurrent tab counts as reuse and both tabs are logged out.
    register()
    old = _raw_refresh(_login(client))
    assert _refresh(client, old).status_code == 204
    assert _refresh(client, old).status_code == 401
    assert all(t.revoked_at is not None for t in db.scalars(select(RefreshToken)))


def test_refresh_other_family_unaffected(client, register, db):
    register()
    a = _raw_refresh(_login(client))
    b = _raw_refresh(_login(client))
    _refresh(client, a)
    _refresh(client, a)  # reuse kills family A only
    assert _refresh(client, b).status_code == 204


def test_expired_refresh_is_401(client, register, db):
    register()
    raw = _raw_refresh(_login(client))
    row = db.scalars(select(RefreshToken)).one()
    row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db.commit()
    assert _refresh(client, raw).status_code == 401


def test_refresh_missing_or_bogus_is_401(client, register):
    assert client.post("/auth/refresh").status_code == 401
    assert _refresh(client, "nope").status_code == 401
    assert _refresh(client, "x" * 5000).status_code == 401


def test_refresh_works_after_access_expired(client, register, db, monkeypatch):
    # Review Focus 1: expired access cookie -> 401 with WWW-Authenticate, refresh still works.
    register()
    login = _login(client)
    user_id = db.scalars(select(User.id)).one()
    client.cookies.set("fd_access", _expired_token(user_id))
    r = client.get("/me")
    assert r.status_code == 401 and r.headers["www-authenticate"] == "Bearer"
    csrf = client.cookies.get("fd_csrf")
    r = client.put("/profiles/me", json={"headline": "x"}, headers={"X-CSRF-Token": csrf})
    assert r.status_code == 401  # expired cookie: the route says 401, not 500
    r = _refresh(client, _raw_refresh(login))
    assert r.status_code == 204
    fresh = _cookie_headers(r)["fd_access"].split(";")[0]
    client.cookies.clear()
    assert client.get("/me", headers={"Cookie": fresh}).status_code == 200


def _expired_token(user_id):
    import jwt

    from firstdev.config import get_settings

    now = datetime.now(UTC)
    claims = {"sub": user_id, "iat": now - timedelta(hours=1), "exp": now - timedelta(minutes=1)}
    return jwt.encode(claims, get_settings().jwt_secret.get_secret_value(), algorithm="HS256")


def test_logout_revokes_and_clears(client, register, db):
    register()
    raw = _raw_refresh(_login(client))
    csrf = client.cookies.get("fd_csrf")
    r = client.post(
        "/auth/logout",
        headers={"Cookie": f"fd_access=x; fd_refresh={raw}; fd_csrf={csrf}", "X-CSRF-Token": csrf},
    )
    assert r.status_code == 204
    cleared = [h.lower() for h in r.headers.get_list("set-cookie")]
    assert len(cleared) == 3 and all("max-age=0" in h for h in cleared)
    assert _refresh(client, raw).status_code == 401
    assert all(t.revoked_at is not None for t in db.scalars(select(RefreshToken)))


def test_logout_with_bearer_and_no_cookies(client, register, login):
    register()
    assert client.post("/auth/logout", headers=login()).status_code == 204


def test_delete_me_clears_cookies(client, register, db):
    register()
    _login(client)
    csrf = client.cookies.get("fd_csrf")
    r = client.request("DELETE", "/me", json={"password": PASSWORD}, headers={"X-CSRF-Token": csrf})
    assert r.status_code == 204
    assert len([h for h in r.headers.get_list("set-cookie") if "max-age=0" in h.lower()]) == 3
    assert db.scalars(select(RefreshToken)).all() == []  # cascaded


def test_refresh_token_stored_only_as_sha256(client, register, db):
    register()
    raw = _raw_refresh(_login(client))
    row = db.scalars(select(RefreshToken)).one()
    assert row.token_hash == hashlib.sha256(raw.encode()).hexdigest()
    assert raw not in str(row.__dict__) and len(raw) >= 43


def test_each_login_new_family(client, register, db):
    register()
    _login(client)
    _login(client)
    assert len({t.family_id for t in db.scalars(select(RefreshToken))}) == 2


def test_non_bearer_authorization_does_not_skip_csrf(client, register):
    register("basic@example.com")
    client.post("/auth/login", json={"email": "basic@example.com", "password": PASSWORD})
    r = client.put(
        "/profiles/me", json={"headline": "x"}, headers={"Authorization": "Basic Zm9vOmJhcg=="}
    )
    assert r.status_code == 403


def test_refresh_cookie_path_follows_proxy_prefix(client, register, monkeypatch):
    from firstdev.config import get_settings

    monkeypatch.setattr(get_settings(), "cookie_path_prefix", "/api")
    register()
    r = client.post("/auth/login", json={"email": "dev@example.com", "password": PASSWORD})
    ref = next(h for h in r.headers.get_list("set-cookie") if h.startswith("fd_refresh="))
    assert "Path=/api/auth" in ref
