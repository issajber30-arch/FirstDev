# Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform.
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from conftest import PASSWORD

from firstdev.config import get_settings
from firstdev.models import User


def _secret():
    return get_settings().jwt_secret.get_secret_value()


def _token(sub="x", exp_delta=timedelta(minutes=5), **kw):
    now = datetime.now(UTC)
    claims = {"sub": sub, "iat": now, "exp": now + exp_delta, **kw}
    return jwt.encode(claims, _secret(), algorithm="HS256")


def test_register_login_me(client, register, login):
    created = register("Dev@Example.com")
    assert created["email"] == "dev@example.com" and created["role"] == "developer"
    assert "password" not in str(created) and "hash" not in str(created)
    r = client.get("/me", headers=login())
    assert r.status_code == 200 and r.json() == created


def test_login_token_shape(client, register):
    register()
    r = client.post("/auth/login", json={"email": "DEV@example.com", "password": PASSWORD})
    assert r.json()["token_type"] == "bearer"
    claims = jwt.decode(r.json()["access_token"], _secret(), algorithms=["HS256"])
    assert set(claims) == {"sub", "iat", "exp"}
    assert claims["exp"] - claims["iat"] == 15 * 60


def test_duplicate_email_case_insensitive(client, register):
    register("a@example.com")
    r = client.post(
        "/auth/register",
        json={"email": "A@EXAMPLE.com", "password": PASSWORD, "role": "recruiter"},
    )
    assert r.status_code == 409
    assert "a@example.com" not in r.text.lower()


@pytest.mark.parametrize(
    "body",
    [
        {"email": "a@example.com", "password": "short", "role": "developer"},
        {"email": "a@example.com", "password": "x" * 11, "role": "developer"},
        {"email": "a@example.com", "password": "x" * 129, "role": "developer"},
        {"email": "not-an-email", "password": PASSWORD, "role": "developer"},
        {"email": "", "password": PASSWORD, "role": "developer"},
        {"email": "a@example.com", "password": PASSWORD, "role": "admin"},
        {"email": "a@example.com", "password": PASSWORD, "role": "root"},
        {"email": "a@example.com", "password": PASSWORD},
        {"email": "a@example.com", "password": PASSWORD, "role": "developer", "is_admin": True},
    ],
)
def test_register_invalid_422(client, body):
    assert client.post("/auth/register", json=body).status_code == 422


def test_password_boundaries_ok(client):
    for i, n in enumerate((12, 128)):
        body = {"email": f"b{i}@example.com", "password": "p" * n, "role": "recruiter"}
        assert client.post("/auth/register", json=body).status_code == 201


def test_login_failures_are_uniform(client, register):
    register()
    wrong = client.post("/auth/login", json={"email": "dev@example.com", "password": "nope"})
    unknown = client.post("/auth/login", json={"email": "nobody@example.com", "password": "nope"})
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json() == {"detail": "invalid email or password"}


def test_login_extra_field_422(client):
    r = client.post("/auth/login", json={"email": "a@b.co", "password": "x", "foo": 1})
    assert r.status_code == 422


def test_rate_limit_429_on_sixth(client, register):
    register()
    codes = [
        client.post("/auth/login", json={"email": "dev@example.com", "password": "bad"}).status_code
        for _ in range(6)
    ]
    assert codes == [401] * 5 + [429]
    # even the right password is blocked while the window is full
    r = client.post("/auth/login", json={"email": "dev@example.com", "password": PASSWORD})
    assert r.status_code == 429


def test_rate_limit_per_ip_across_emails(client):
    codes = [
        client.post(
            "/auth/login", json={"email": f"u{i}@example.com", "password": "bad"}
        ).status_code
        for i in range(6)
    ]
    assert codes == [401] * 5 + [429]


def test_me_requires_valid_token(client, register):
    assert client.get("/me").status_code == 401
    assert client.get("/me", headers={"Authorization": "Bearer garbage"}).status_code == 401
    assert client.get("/me", headers={"Authorization": "Basic abc"}).status_code == 401


def test_expired_token(client, register):
    user = register()
    t = _token(sub=user["id"], exp_delta=timedelta(seconds=-10))
    assert client.get("/me", headers={"Authorization": f"Bearer {t}"}).status_code == 401


def test_tampered_token(client, register):
    user = register()
    head, payload, sig = _token(sub=user["id"]).split(".")
    bad_sig = sig[:-2] + ("AA" if sig[-2:] != "AA" else "BB")
    for t in (f"{head}.{payload}.{bad_sig}", f"{head}.{payload}x.{sig}"):
        assert client.get("/me", headers={"Authorization": f"Bearer {t}"}).status_code == 401


def test_wrong_secret_token(client, register):
    user = register()
    t = jwt.encode(
        {"sub": user["id"], "iat": datetime.now(UTC), "exp": datetime.now(UTC) + timedelta(1)},
        "y" * 40,
        algorithm="HS256",
    )
    assert client.get("/me", headers={"Authorization": f"Bearer {t}"}).status_code == 401


def test_alg_none_token(client, register):
    user = register()
    now = datetime.now(UTC)
    t = jwt.encode(
        {"sub": user["id"], "iat": now, "exp": now + timedelta(minutes=5)},
        None,
        algorithm="none",
    )
    assert client.get("/me", headers={"Authorization": f"Bearer {t}"}).status_code == 401


def test_token_missing_claims(client, register):
    user = register()
    no_exp = jwt.encode({"sub": user["id"]}, _secret(), algorithm="HS256")
    no_sub = jwt.encode(
        {"iat": datetime.now(UTC), "exp": datetime.now(UTC) + timedelta(1)},
        _secret(),
        algorithm="HS256",
    )
    for t in (no_exp, no_sub):
        assert client.get("/me", headers={"Authorization": f"Bearer {t}"}).status_code == 401


def test_token_for_deleted_user(client, register, login, db):
    register()
    headers = login()
    db.delete(db.query(User).one())
    db.commit()
    assert client.get("/me", headers=headers).status_code == 401


def test_limiter_memory_is_bounded():
    from firstdev import auth

    limiter = auth.FailureLimiter(max_keys=100)
    for i in range(1000):
        limiter.fail(f"email:user{i}@example.com")
    assert len(limiter._hits) <= 100
    # The most recent failures are the ones kept.
    assert "email:user999@example.com" in limiter._hits
