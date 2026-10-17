# Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform.
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from firstdev import auth
from firstdev.models import (
    BadgeSource,
    CvDocument,
    CvParse,
    CvStatus,
    DeveloperProfile,
    RepoAnalysis,
    Repository,
    Role,
    SkillBadge,
    User,
)

URL = "/profiles/me"
KEYS = {"handle", "display_name", "headline", "tier", "verified_badges"}
BADGE_KEYS = {"skill", "source", "verified_at"}
NOT_FOUND = {"detail": "not found"}
T1, T2 = datetime(2026, 3, 1, tzinfo=UTC), datetime(2026, 5, 1, tzinfo=UTC)


def put(client, h, **kw):
    return client.put(URL, json={"headline": "Backend dev", **kw}, headers=h)


# --- handles --------------------------------------------------------------------------------


@pytest.mark.parametrize("handle", ["abc", "a1b", "a-b-c", "x" * 30, "9lives", "a--b"])
def test_valid_handles(client, dev_headers, handle):
    r = put(client, dev_headers, handle=handle)
    assert r.status_code == 200 and r.json()["handle"] == handle


@pytest.mark.parametrize(
    "handle", ["ab", "a", "-abc", "abc-", "a" * 31, "ab c", "a_b", "ééé", "a.b", "", "ab\n"]
)
def test_invalid_handles(client, dev_headers, handle):
    assert put(client, dev_headers, handle=handle).status_code == 422


def test_handle_is_lowercased(client, dev_headers):
    assert put(client, dev_headers, handle="Dana-DEV").json()["handle"] == "dana-dev"


def test_kelvin_sign_is_not_ascii_folded(client, dev_headers):
    assert put(client, dev_headers, handle="Kevin").status_code == 422


@pytest.mark.parametrize(
    "word",
    ["admin", "api", "demo", "login", "auth", "assessments", "postings", "applications",
     "connections", "profiles", "jobs", "health", "docs", "ADMIN", "Docs"],
)  # fmt: skip
def test_reserved_handles(client, dev_headers, word):
    assert put(client, dev_headers, handle=word).status_code == 422


def test_duplicate_handle_is_409_but_own_handle_is_idempotent(client, register, login):
    register("a@example.com")
    register("b@example.com")
    ha, hb = login("a@example.com"), login("b@example.com")
    assert put(client, ha, handle="same").status_code == 200
    assert put(client, ha, handle="SAME").status_code == 200
    assert put(client, hb, handle="same").status_code == 409


def test_put_without_handle_clears_it_and_the_public_flag(client, dev_headers):
    put(client, dev_headers, handle="abc", public_profile=True)
    r = client.put(URL, json={"headline": "x"}, headers=dev_headers)
    assert r.json()["handle"] is None and r.json()["public_profile"] is False


def test_profile_out_has_handle_and_flag(client, dev_headers):
    assert client.get(URL, headers=dev_headers).json()["public_profile"] is False


def test_public_profile_needs_a_handle(client, dev_headers):
    assert put(client, dev_headers, public_profile=True).status_code == 422


def test_sandbox_user_cannot_go_public(client, db, dev_headers):
    u = db.query(User).one()
    u.world_id = str(uuid.uuid4())
    db.commit()
    assert put(client, dev_headers, handle="abc", public_profile=True).status_code == 422
    # No handle at all in a sandbox: it would let visitors probe real users' handles.
    r = put(client, dev_headers, handle="abc", public_profile=False)
    assert r.status_code == 422 and "handle" in r.json()["detail"]
    assert put(client, dev_headers, public_profile=False).status_code == 200


def test_recruiter_cannot_reach_the_profile_route(client, db, register, login):
    # Recruiters have no profile (404 on the whole route), so they can never go public.
    register("rec@example.com", role="recruiter")
    h = login("rec@example.com")
    r = put(client, h, handle="abc", public_profile=True)
    assert r.status_code == 404
    assert db.query(User).one().public_profile is False


# --- GET /u/{handle} -------------------------------------------------------------------------


def _verified_dev(db, user, *, repos=(("o", "r1", T1, ("python",)),), cv=("python", "sql")):
    """Parsed CV plus analyzed repos: (owner, name, analysis_created_at, languages)."""
    doc = CvDocument(profile_id=user.id, sha256="h", size=1, status=CvStatus.parsed)
    db.add(doc)
    db.flush()
    data = {"skills": [{"name": s, "years": None} for s in cv], "experience": [], "gaps": []}
    db.add(CvParse(cv_document_id=doc.id, schema_version=1, model="m", data=data))
    for owner, name, at, langs in repos:
        repo = Repository(profile_id=user.id, owner=owner, name=name)
        db.add(repo)
        db.flush()
        db.add(
            RepoAnalysis(
                repository_id=repo.id, commit_sha="a" * 40, created_at=at,
                metrics={"languages": {s.title(): 50_000 for s in langs}},
                assessment={}, tutorial_likelihood=0.0, model="m",
            )
        )  # fmt: skip
    db.commit()


@pytest.fixture
def pub(client, db, register, login):
    """A real-world developer who opted in as 'dana', with CV, two repos and badges."""
    register("dana@example.com")
    h = login("dana@example.com")
    user = db.query(User).filter(User.email == "dana@example.com").one()
    _verified_dev(
        db, user,
        repos=(("o", "r1", T1, ("python",)), ("o", "r2", T2, ("python", "go"))),
    )  # fmt: skip
    now = datetime.now(UTC)
    db.add_all([
        SkillBadge(profile_id=user.id, skill="sql", level=85, source=BadgeSource.assessment,
                   created_at=T1, expires_at=now + timedelta(days=30)),
        SkillBadge(profile_id=user.id, skill="rust", level=90, source=BadgeSource.assessment,
                   created_at=T1, expires_at=now - timedelta(days=1)),
    ])  # fmt: skip
    db.commit()
    assert (
        put(client, h, handle="dana", public_profile=True, experience_tier="mid").status_code == 200
    )
    db.refresh(user)  # the PUT ran in another session
    return user


def test_public_profile_exact_allowlist(client, pub):
    r = client.get("/u/dana")
    assert r.status_code == 200
    body = r.json()
    assert set(body) == KEYS
    assert body["handle"] == "dana" and body["display_name"] == "dana"
    assert body["headline"] == "Backend dev" and body["tier"] == "mid"
    assert all(set(b) == BADGE_KEYS for b in body["verified_badges"])
    raw = r.text.lower()
    for banned in ("dana@example.com", "email", "cv", "score", "level", "bio", "location"):
        assert banned not in raw.replace('"verified_badges"', "")


def test_badges_are_verified_only_with_dates(client, pub):
    got = {
        (b["skill"], b["source"]): b["verified_at"]
        for b in client.get("/u/dana").json()["verified_badges"]
    }
    # python: repo (latest analysis of o/r1 and o/r2), go: only o/r2, sql: assessment; the
    # expired rust badge and the CV-only claim never show.
    assert set(got) == {("python", "repo"), ("go", "repo"), ("sql", "assessment")}
    assert datetime.fromisoformat(got[("python", "repo")]) == T2
    assert datetime.fromisoformat(got[("go", "repo")]) == T2
    assert datetime.fromisoformat(got[("sql", "assessment")]) == T1


def test_repo_verified_at_uses_only_contributing_repos(client, db, pub):
    # go proven by r2 only; add a newer repo that does not contribute python or go
    repo = Repository(profile_id=pub.id, owner="o", name="r3")
    db.add(repo)
    db.flush()
    db.add(RepoAnalysis(repository_id=repo.id, commit_sha="b" * 40,
                        created_at=datetime(2026, 9, 1, tzinfo=UTC),
                        metrics={"languages": {"Rust": 50_000}}, assessment={},
                        tutorial_likelihood=0.0, model="m"))  # fmt: skip
    db.commit()
    got = {b["skill"]: b["verified_at"] for b in client.get("/u/dana").json()["verified_badges"]
           if b["source"] == "repo"}  # fmt: skip
    assert datetime.fromisoformat(got["python"]) == T2
    assert datetime.fromisoformat(got["rust"]) == datetime(2026, 9, 1, tzinfo=UTC)


def test_cv_only_developer_has_no_badges(client, db, register, login):
    register("cv@example.com")
    h = login("cv@example.com")
    _verified_dev(db, db.query(User).one(), repos=())
    put(client, h, handle="cvonly", public_profile=True)
    assert client.get("/u/cvonly").json()["verified_badges"] == []


def test_lookup_is_case_insensitive_and_cached(client, pub):
    r = client.get("/u/DANA")
    assert r.status_code == 200 and r.json()["handle"] == "dana"
    assert r.headers["cache-control"] == "public, max-age=60"


def test_cache_control_survives_credentials(client, pub):
    r = client.get("/u/dana", headers={"Authorization": "Bearer junk"})
    assert r.headers["cache-control"] == "public, max-age=60"


def test_private_unknown_and_invalid_handles_look_identical(client, db, pub):
    pub.public_profile = False
    db.commit()
    for path in (
        "/u/dana",
        "/u/nobody",
        "/u/-bad-",
        "/u/a",
        "/u/" + "x" * 80,
        "/u/%C3%A9%C3%A9%C3%A9",
    ):
        r = client.get(path)
        assert r.status_code == 404 and r.json() == NOT_FOUND, path
        assert "cache-control" not in r.headers


def test_sandbox_user_is_404_identical_to_unknown(client, db, pub):
    pub.world_id = str(uuid.uuid4())
    db.commit()
    a, b = client.get("/u/dana"), client.get("/u/nobody")
    assert a.status_code == b.status_code == 404
    assert a.json() == b.json() == NOT_FOUND and a.headers.get("cache-control") == b.headers.get(
        "cache-control"
    )


def test_recruiter_handle_is_never_public(client, db, pub):
    pub.role = Role.recruiter
    db.commit()
    assert client.get("/u/dana").status_code == 404


def test_61st_request_in_a_minute_is_429(client, pub):
    assert all(client.get("/u/dana").status_code == 200 for _ in range(60))
    r = client.get("/u/dana")
    assert r.status_code == 429
    assert client.get("/u/nobody").status_code == 429  # misses count too: no free probing


def test_limit_is_per_ip_and_spoofed_header_is_ignored(client, pub):
    for _ in range(60):
        client.get("/u/dana")
    spoof = {"X-FirstDev-Client-IP": "9.9.9.9"}  # no proxy secret: ignored
    assert client.get("/u/dana", headers=spoof).status_code == 429


def test_limit_keys_on_trusted_proxy_ip(client, pub, set_env):
    set_env(proxy_secret="s" * 32)
    ok = {"X-FirstDev-Proxy-Secret": "s" * 32}
    for _ in range(60):
        client.get("/u/dana", headers={**ok, "X-FirstDev-Client-IP": "1.1.1.1"})
    assert (
        client.get("/u/dana", headers={**ok, "X-FirstDev-Client-IP": "1.1.1.1"}).status_code == 429
    )
    assert (
        client.get("/u/dana", headers={**ok, "X-FirstDev-Client-IP": "2.2.2.2"}).status_code == 200
    )


# --- RateLimiter -----------------------------------------------------------------------------


def test_rate_limiter_window_and_keys(monkeypatch):
    import firstdev.auth as a

    t = [1000.0]
    monkeypatch.setattr(a.time, "monotonic", lambda: t[0])
    rl = a.RateLimiter(max_hits=3, window_seconds=60)
    assert [rl.hit("k") for _ in range(4)] == [True, True, True, False]
    assert rl.hit("other") is True
    t[0] += 61
    assert rl.hit("k") is True  # old hits left the window
    rl.reset()
    assert rl.hit("k") is True


def test_rate_limiter_bounds_memory(monkeypatch):
    rl = auth.RateLimiter(max_hits=5, window_seconds=60, max_keys=10)
    for i in range(50):
        rl.hit(f"ip{i}")
    assert len(rl._hits) <= 10


def test_profile_user_rows_unchanged_by_reads(client, db, pub):
    before = db.query(DeveloperProfile).count()
    client.get("/u/dana")
    assert db.query(DeveloperProfile).count() == before
