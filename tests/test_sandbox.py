# Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform.
"""Sandboxes (M18): Turnstile, per-IP limit, the demo-world fixture and clone, quotas, sweep."""

import hashlib
import logging
import re
from datetime import UTC, datetime, timedelta

import httpx
import pytest
import respx
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker
from test_matches_api import drain, review

from firstdev import auth
from firstdev.assessments import generate, grade  # noqa: F401  (registers handlers)
from firstdev.config import Settings
from firstdev.demo import clone, quota
from firstdev.demo.turnstile import VERIFY_URL
from firstdev.jobs import HANDLERS, run_once, sweep_expired
from firstdev.llm import FakeLLM
from firstdev.models import (
    Assessment,
    Base,
    DeveloperProfile,
    Job,
    JobKind,
    JobPosting,
    JobStatus,
    LlmLedger,
    MatchScore,
    SandboxCreation,
    SkillBadge,
    SkillProfile,
    User,
)
from firstdev.pipelines import cv_parser, match_jobs, repo_analyzer  # noqa: F401
from firstdev.pipelines.cv_parser import validate_extraction
from firstdev.schemas.cv import CVExtraction
from firstdev.skills import normalize_skill

FX = clone.load_fixture()
HEBREW = re.compile(r"[֐-׿]")


@pytest.fixture
def factory(engine):
    return sessionmaker(engine, expire_on_commit=False)


def make_sandbox(client, role="developer"):
    """Create a sandbox; returns (response json, visitor user id, Bearer headers)."""
    r = client.post("/demo/sandbox", json={"role": role, "turnstile_token": "t"})
    assert r.status_code == 201, r.text
    uid = auth.decode_token(client.cookies.get("fd_access"))
    client.cookies.clear()  # tests below use Bearer unless they test cookies
    return r.json(), uid, {"Authorization": f"Bearer {auth.create_token(uid)}"}


def counts(db):
    return {
        t.name: db.scalar(select(func.count()).select_from(t)) for t in Base.metadata.sorted_tables
    }


# --- the fixture itself ------------------------------------------------------------------------


def test_fixture_shape():
    assert "Copyright (c) 2026 Issa Jber" in FX["_copyright"]
    assert len(FX["postings"]) == 4 and len(FX["developers"]) == 6
    assert "Helix Labs" in FX["recruiter"]["name"] and "Tel Aviv" in FX["recruiter"]["name"]
    assert sum(bool(HEBREW.search(d["cv_text"])) for d in FX["developers"]) == 2
    repos = [r for d in FX["developers"] for r in d["repos"]]
    assert any(r["tutorial_likelihood"] == 0.85 for r in repos)
    assert sum(1 for d in FX["developers"] if d["assessment"]) == 1
    for r in repos:  # skill profiles read these two metrics
        assert r["metrics"]["languages"] and "dependencies" in r["metrics"]
    keys = {d["key"] for d in FX["developers"]}
    pkeys = {p["key"] for p in FX["postings"]}
    assert FX["visitor"]["developer_template"] in keys
    for dk, per in FX["matches"].items():
        assert dk in keys and set(per) <= pkeys


@pytest.mark.parametrize("dev", FX["developers"], ids=lambda d: d["key"])
def test_fixture_evidence_and_paths(dev):
    text = dev["cv_text"]
    cv = dev["cv"]
    for section in ("skills", "experience", "education"):
        for item in cv[section]:
            assert item["evidence_quote"] in text, item["evidence_quote"]  # verbatim
            assert len(item["evidence_quote"]) <= 200
    for s in cv["skills"]:
        assert normalize_skill(s["name"]) is not None
    data = validate_extraction(CVExtraction(**cv), text)
    assert data.dropped == []  # nothing the real validator would have thrown away
    for r in dev["repos"]:
        for bp in r["assessment"]["best_practices"]:
            assert bp["evidence_path"] in r["files"], bp
    if dev["key"] == "changer":
        assert data.gaps  # the CV gap the developer's own match page reports


def test_fixture_posting_skills_are_normalized():
    for p in FX["postings"]:
        for s in p["required_skills"] + p["optional_skills"]:
            assert normalize_skill(s) == s
        assert len(p["description"]) > 100


# --- config ------------------------------------------------------------------------------------


def test_turnstile_disabled_refused_in_prod():
    kw = dict(jwt_secret="x" * 40, env="prod", proxy_secret="p", cookie_secure=True)
    Settings(**kw, turnstile_disabled=False)  # fine
    with pytest.raises(ValueError, match="TURNSTILE_DISABLED"):
        Settings(**kw, turnstile_disabled=True)
    Settings(jwt_secret="x" * 40, env="dev", turnstile_disabled=True)  # allowed outside prod


# --- Turnstile ---------------------------------------------------------------------------------


@pytest.fixture
def turnstile_on(set_env):
    set_env(turnstile_disabled="false", turnstile_secret="sekret")


@respx.mock
def test_turnstile_success_sets_cookies(client, turnstile_on):
    route = respx.post(VERIFY_URL).mock(return_value=httpx.Response(200, json={"success": True}))
    r = client.post("/demo/sandbox", json={"role": "developer", "turnstile_token": "tok"})
    assert r.status_code == 201
    assert set(r.json()) == {"role", "world_id", "expires_at"}
    assert {"fd_access", "fd_refresh", "fd_csrf"} <= set(client.cookies)
    body = route.calls.last.request.content.decode()
    assert "secret=sekret" in body and "response=tok" in body and "remoteip=" in body
    assert route.calls.last.request.extensions["timeout"]["read"] == 5.0


@respx.mock
def test_turnstile_failure_is_403_and_creates_nothing(client, turnstile_on, db):
    respx.post(VERIFY_URL).mock(
        return_value=httpx.Response(200, json={"success": False, "error-codes": ["x"]})
    )
    r = client.post("/demo/sandbox", json={"role": "developer", "turnstile_token": "bad"})
    assert r.status_code == 403
    assert db.scalar(select(func.count()).select_from(User)) == 0


@respx.mock
@pytest.mark.parametrize(
    "effect", [httpx.ConnectTimeout("t"), httpx.ConnectError("c"), httpx.Response(502, text="bad")]
)
def test_turnstile_unavailable_is_503(client, turnstile_on, effect):
    respx.post(VERIFY_URL).mock(
        side_effect=effect if isinstance(effect, Exception) else None,
        return_value=None if isinstance(effect, Exception) else effect,
    )
    r = client.post("/demo/sandbox", json={"role": "developer", "turnstile_token": "tok"})
    assert r.status_code == 503 and r.json()["detail"] == "verification unavailable, try again"


@respx.mock
def test_turnstile_missing_token_or_secret(client, set_env):
    route = respx.post(VERIFY_URL).mock(return_value=httpx.Response(200, json={"success": True}))
    set_env(turnstile_disabled="false", turnstile_secret="sekret")
    assert client.post("/demo/sandbox", json={"role": "developer"}).status_code == 403
    assert not route.called  # an empty token never costs a network call
    set_env(turnstile_disabled="false", turnstile_secret="")
    r = client.post("/demo/sandbox", json={"role": "developer", "turnstile_token": "t"})
    assert r.status_code == 503  # misconfigured: fail closed, never open


def test_bad_role_is_422(client):
    assert client.post("/demo/sandbox", json={"role": "admin"}).status_code == 422


# --- per-IP limit ------------------------------------------------------------------------------


def test_fourth_sandbox_from_one_ip_is_429(client, db, set_env):
    for _ in range(3):
        make_sandbox(client)
    r = client.post("/demo/sandbox", json={"role": "developer", "turnstile_token": "t"})
    assert r.status_code == 429
    assert (
        db.scalar(select(func.count()).select_from(User).where(User.world_id.is_not(None))) == 3 * 8
    )
    # Only the hash is stored.
    rows = db.scalars(select(SandboxCreation)).all()
    assert len(rows) == 3
    expect = hashlib.sha256(("testclient" + "test-secret-" + "x" * 40).encode()).hexdigest()
    assert {r.ip_hash for r in rows} == {expect}
    assert "testclient" not in "".join(r.ip_hash for r in rows)


def test_other_ip_is_not_limited(client, set_env):
    set_env(proxy_secret="psecret")
    h = lambda ip: {"X-FirstDev-Proxy-Secret": "psecret", "X-FirstDev-Client-IP": ip}  # noqa: E731
    for _ in range(3):
        assert (
            client.post(
                "/demo/sandbox", json={"role": "recruiter"}, headers=h("1.1.1.1")
            ).status_code
            == 201
        )
    assert (
        client.post("/demo/sandbox", json={"role": "recruiter"}, headers=h("1.1.1.1")).status_code
        == 429
    )
    assert (
        client.post("/demo/sandbox", json={"role": "recruiter"}, headers=h("2.2.2.2")).status_code
        == 201
    )
    # A spoofed header without the proxy secret does not buy a fresh allowance.
    spoof = {"X-FirstDev-Client-IP": "9.9.9.9"}
    assert (
        client.post("/demo/sandbox", json={"role": "recruiter"}, headers=spoof).status_code == 201
    )
    assert (
        client.post("/demo/sandbox", json={"role": "recruiter"}, headers=spoof).status_code == 201
    )
    assert (
        client.post("/demo/sandbox", json={"role": "recruiter"}, headers=spoof).status_code == 201
    )
    assert (
        client.post("/demo/sandbox", json={"role": "recruiter"}, headers=spoof).status_code == 429
    )


# --- cloning -----------------------------------------------------------------------------------


def test_developer_sandbox_world(client, db):
    out, uid, h = make_sandbox(client, "developer")
    visitor = db.get(User, uid)
    assert out["role"] == "developer" and out["world_id"] == visitor.world_id
    assert visitor.display_name == "You (Demo Developer)"
    world = db.scalars(select(User).where(User.world_id == visitor.world_id)).all()
    assert len(world) == 8  # recruiter persona + 6 personas + the visitor
    assert {u.display_name for u in world} >= {FX["recruiter"]["name"], "Yael Cohen", "Eran Katz"}
    now = datetime.now(UTC)
    for u in world:  # 24 h life on every user
        assert timedelta(hours=23, minutes=59) < u.expires_at - now <= timedelta(hours=24)
        assert u.world_id == visitor.world_id and u.email.endswith("@sandbox.invalid")
    ids = {u.id for u in world}
    assert (
        db.scalar(
            select(func.count())
            .select_from(DeveloperProfile)
            .where(DeveloperProfile.user_id.in_(ids))
        )
        == 7
    )
    assert (
        db.scalar(
            select(func.count())
            .select_from(MatchScore)
            .join(DeveloperProfile, DeveloperProfile.user_id == MatchScore.profile_id)
            .where(DeveloperProfile.user_id.in_(ids))
        )
        == 28
    )
    # the visitor is a clone of the strong persona
    sp = {u.display_name: u for u in world}
    a, b = (db.get(SkillProfile, x.id) for x in (sp["Yael Cohen"], visitor))
    assert a.skills == b.skills and a.fingerprint == b.fingerprint
    jobs = db.scalars(select(Job).where(Job.user_id.in_(ids))).all()
    assert sorted(j.kind for j in jobs) == sorted(
        [JobKind.embed_profile] * 7 + [JobKind.embed_posting] * 4
    )
    assert all(j.status == JobStatus.queued for j in jobs)
    rec = next(u for u in world if u.role == "recruiter")
    assert {j.user_id for j in jobs if j.kind == JobKind.embed_posting} == {rec.id}
    assert client.get("/me", headers=h).json()["display_name"] == "You (Demo Developer)"


def test_recruiter_sandbox_world(client, db):
    out, uid, h = make_sandbox(client, "recruiter")
    visitor = db.get(User, uid)
    assert visitor.display_name == "You (Demo Recruiter)" and visitor.role == "recruiter"
    assert (
        db.scalar(select(func.count()).select_from(User).where(User.world_id == visitor.world_id))
        == 7
    )
    posts = client.get("/postings/mine", headers=h).json()
    assert len(posts) == 4 and not any(p["auto_assessment"] for p in posts)
    assert {p["status"] for p in posts} == {"open"}
    assert db.scalar(select(func.count()).select_from(MatchScore)) == 24


def test_personas_can_never_log_in(client, db):
    _, uid, _ = make_sandbox(client)
    world = db.scalars(select(User).where(User.world_id == db.get(User, uid).world_id)).all()
    for u in world:
        assert u.password_hash.startswith("$argon2")
        assert not auth.verify_password(u.password_hash, "password")
        assert not auth.verify_password(u.password_hash, "")
    r = client.post(
        "/auth/login", json={"email": world[0].email, "password": "correct horse battery"}
    )
    assert r.status_code == 401


def test_skill_levels_demonstrate_each_persona(client, db):
    _, uid, _ = make_sandbox(client)
    w = db.get(User, uid).world_id
    levels = {}
    for u in db.scalars(select(User).where(User.world_id == w, User.role == "developer")):
        sp = db.get(SkillProfile, u.id)
        levels.setdefault(u.display_name, {s["skill"]: s["level"] for s in sp.skills})
    assert (
        levels["Yael Cohen"]["fastapi"] == "repo" and levels["Yael Cohen"]["postgresql"] == "repo"
    )
    assert levels["Omer Barak"]["react"] == "cv" and "repo" not in levels["Omer Barak"].values()
    assert levels["Tomer Shapira"]["react"] == "cv"  # the 0.85-tutorial repo proves nothing
    assert levels["Dana Mizrahi"]["react"] == "assessment"
    assert levels["Eran Katz"]["pandas"] == "repo" and levels["Eran Katz"]["sql"] == "cv"
    assert (
        levels["Lior Ben-David"]["redis"] == "repo" and levels["Lior Ben-David"]["node.js"] == "cv"
    )
    badge = db.scalar(select(SkillBadge))
    assert badge.skill == "react" and badge.source == "assessment" and badge.level == 83
    assert badge.expires_at > datetime.now(UTC) + timedelta(days=300)
    a = db.scalar(select(Assessment))
    assert a.status == "graded" and a.overall_pct == 83.3


def test_match_scores_are_fresh_and_hand_written(client, db):
    _, uid, _ = make_sandbox(client)
    w = db.get(User, uid).world_id
    ids = list(db.scalars(select(User.id).where(User.world_id == w)))
    explained = 0
    for ms in db.scalars(select(MatchScore).where(MatchScore.profile_id.in_(ids))):
        posting = db.get(JobPosting, ms.posting_id)
        sp = db.get(SkillProfile, ms.profile_id)
        assert not match_jobs.is_stale(ms, posting, sp)  # fingerprints match
        if ms.explained:
            explained += 1
            assert ms.model == "demo-fixture" and ms.reasons and ms.feedback["strengths"]
            have = {s["skill"] for s in sp.skills}
            wanted = set(posting.required_skills) | set(posting.optional_skills)
            assert set(ms.feedback["missing_skills"]) <= wanted - have
        else:
            assert ms.model == "formula"
    assert explained == sum(len(v) for v in FX["matches"].values()) + len(FX["matches"]["strong"])


def test_visitor_sees_fixture_feedback_without_llm(client, db):
    _, uid, h = make_sandbox(client)
    rec = db.scalar(
        select(User).where(User.world_id == db.get(User, uid).world_id, User.role == "recruiter")
    )
    backend = db.scalar(
        select(JobPosting).where(
            JobPosting.recruiter_id == rec.id, JobPosting.title.like("%Backend%")
        )
    )
    r = client.get(f"/me/matches/{backend.id}", headers=h)
    assert r.status_code == 200 and r.json()["explained"] is True
    assert "ledger-api" in r.json()["feedback"]["strengths"][0]
    assert (
        db.scalar(select(func.count()).select_from(Job).where(Job.kind == JobKind.score_pair)) == 0
    )


def test_two_sandboxes_are_disjoint(client, db):
    make_sandbox(client)
    make_sandbox(client)
    worlds = list(db.scalars(select(User.world_id).distinct()))
    assert len(worlds) == 2
    per = {w: set(db.scalars(select(User.id).where(User.world_id == w))) for w in worlds}
    a, b = per.values()
    assert not a & b
    posts = {
        w: set(db.scalars(select(JobPosting.id).where(JobPosting.recruiter_id.in_(ids))))
        for w, ids in per.items()
    }
    pa, pb = posts.values()
    assert len(pa) == len(pb) == 4 and not pa & pb
    ms = {
        w: set(db.scalars(select(MatchScore.id).where(MatchScore.posting_id.in_(p))))
        for w, p in posts.items()
    }
    assert not set.intersection(*ms.values())


def test_clone_failure_rolls_back_everything(client, db, monkeypatch, caplog):
    real = clone.score_and_store
    n = {"i": 0}

    def boom(*a, **k):
        n["i"] += 1
        if n["i"] == 10:
            raise RuntimeError("SECRET-INTERNAL-DETAIL")
        return real(*a, **k)

    monkeypatch.setattr(clone, "score_and_store", boom)
    with caplog.at_level(logging.INFO):
        r = client.post("/demo/sandbox", json={"role": "developer", "turnstile_token": "t"})
    assert r.status_code == 500 and r.json() == {"detail": "could not create the sandbox"}
    assert "SECRET-INTERNAL-DETAIL" not in r.text + caplog.text
    assert "RuntimeError" in caplog.text
    assert all(v == 0 for v in counts(db).values()), counts(db)  # not even the IP-limit row


def test_cookie_session_and_csrf(client, set_env):
    r = client.post("/demo/sandbox", json={"role": "developer", "turnstile_token": "t"})
    assert r.status_code == 201
    assert client.get("/me").json()["display_name"] == "You (Demo Developer)"
    url = {"url": "https://github.com/someone/proj"}
    assert client.post("/profiles/me/repos", json=url).status_code == 403  # no CSRF header
    ok = client.post(
        "/profiles/me/repos", json=url, headers={"X-CSRF-Token": client.cookies["fd_csrf"]}
    )
    assert ok.status_code == 202


def test_expired_sandbox_user_is_rejected_before_the_sweep(client, db):
    _, uid, h = make_sandbox(client)
    assert client.get("/me", headers=h).status_code == 200
    db.get(User, uid).expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db.commit()
    assert client.get("/me", headers=h).status_code == 401


# --- sandbox behaviour -------------------------------------------------------------------------


def test_sandbox_postings_cannot_enable_auto_assessment(client):
    _, _, h = make_sandbox(client, "recruiter")
    body = {"title": "Dev", "description": "Do things well.", "required_skills": ["python"],
            "auto_assessment": True, "status": "open"}  # fmt: skip
    r = client.post("/postings", json=body, headers=h)
    assert r.status_code == 201 and r.json()["auto_assessment"] is False
    r = client.put(f"/postings/{r.json()['id']}", json=body, headers=h)
    assert r.status_code == 200 and r.json()["auto_assessment"] is False


def test_real_recruiter_can_still_enable_auto_assessment(client, register, login):
    register("rec@example.com", "recruiter")
    h = login("rec@example.com")
    body = {"title": "Dev", "description": "Do things well.", "required_skills": ["python"],
            "auto_assessment": True}  # fmt: skip
    assert client.post("/postings", json=body, headers=h).json()["auto_assessment"] is True


def test_sandbox_delete_me_deletes_the_whole_world(client, db):
    _, uid, h = make_sandbox(client)
    _, uid2, _ = make_sandbox(client)
    w, w2 = db.get(User, uid).world_id, db.get(User, uid2).world_id
    db.add(
        LlmLedger(
            day=datetime.now(UTC).date(), user_id=uid, world_id=w, kind="cv_parse", reserved_usd=0.1
        )
    )
    db.commit()
    r = client.request("DELETE", "/me", headers=h)  # no password: a visitor has none
    assert r.status_code == 204
    db.expire_all()
    assert db.scalar(select(func.count()).select_from(User).where(User.world_id == w)) == 0
    assert db.scalar(select(func.count()).select_from(User).where(User.world_id == w2)) == 8
    row = db.scalar(select(LlmLedger))
    assert row.user_id is None and row.world_id is None  # spend is kept, the link is not


def test_real_delete_me_still_needs_the_password(client, register, login):
    register()
    h = login()
    assert client.request("DELETE", "/me", headers=h).status_code == 422
    assert (
        client.request(
            "DELETE", "/me", headers=h, json={"password": "wrong wrong wrong"}
        ).status_code
        == 403
    )
    assert (
        client.request(
            "DELETE", "/me", headers=h, json={"password": "correct horse battery"}
        ).status_code
        == 204
    )


# --- quotas ------------------------------------------------------------------------------------

CV = "Python developer with some FastAPI experience.\nWorked at Acme 2024-2025 building APIs."


def test_cv_quota(client):
    _, _, h = make_sandbox(client)
    assert client.post("/profiles/me/cv", data={"text": CV}, headers=h).status_code == 202
    r = client.post("/profiles/me/cv", data={"text": CV + " Second."}, headers=h)
    assert r.status_code == 429 and r.json()["detail"] == "demo limit reached for this sandbox"


def test_repo_quota(client):
    _, _, h = make_sandbox(client)
    assert (
        client.post(
            "/profiles/me/repos", json={"url": "https://github.com/a/b"}, headers=h
        ).status_code
        == 202
    )
    r = client.post("/profiles/me/repos", json={"url": "https://github.com/a/c"}, headers=h)
    assert r.status_code == 429 and r.json()["detail"] == "demo limit reached for this sandbox"


def test_assessment_quota_practice_and_recruiter_send(client, db):
    _, uid, h = make_sandbox(client)
    r = client.post("/me/assessments", json={"skills": ["docker"]}, headers=h)
    assert r.status_code == 202
    r = client.post("/me/assessments", json={"skills": ["git"]}, headers=h)
    assert r.status_code == 429 and r.json()["detail"] == "demo limit reached for this sandbox"
    # A recruiter-sent assessment shares the world's single allowance.
    w = db.get(User, uid).world_id
    assert (
        db.scalar(
            select(func.count())
            .select_from(Job)
            .join(User, User.id == Job.user_id)
            .where(User.world_id == w, Job.kind == JobKind.assessment_generate)
        )
        == 1
    )
    _, ruid, rh = make_sandbox(client, "recruiter")
    dev = db.scalar(
        select(User).where(
            User.world_id == db.get(User, ruid).world_id, User.display_name == "Yael Cohen"
        )
    )
    post = db.scalar(
        select(JobPosting).where(
            JobPosting.recruiter_id == ruid, JobPosting.title.like("%Backend%")
        )
    )
    from firstdev.models import Application

    app = Application(job_posting_id=post.id, profile_id=dev.id)
    other = Application(
        job_posting_id=post.id,
        profile_id=db.scalar(
            select(User.id).where(
                User.world_id == db.get(User, ruid).world_id, User.display_name == "Omer Barak"
            )
        ),
    )
    db.add_all([app, other])
    db.commit()
    assert client.post(f"/applications/{app.id}/assessment", headers=rh).status_code == 202
    r = client.post(f"/applications/{other.id}/assessment", headers=rh)
    assert r.status_code == 429


def test_explaining_score_quota_blocks_apply(client, db):
    _, uid, h = make_sandbox(client)
    for _ in range(3):  # 3 of 4 used; plain (non-explaining) scores never count
        db.add(Job(user_id=uid, kind=JobKind.score_pair, payload={"explain": True}))
    db.add(Job(user_id=uid, kind=JobKind.score_pair, payload={"explain": False}))
    db.commit()
    rec = db.scalar(
        select(User).where(User.world_id == db.get(User, uid).world_id, User.role == "recruiter")
    )
    posts = db.scalars(select(JobPosting).where(JobPosting.recruiter_id == rec.id)).all()
    assert client.post(f"/postings/{posts[0].id}/apply", headers=h).status_code == 201  # the 4th
    r = client.post(f"/postings/{posts[1].id}/apply", headers=h)  # the 5th
    assert r.status_code == 429 and r.json()["detail"] == "demo limit reached for this sandbox"


def test_budget_refused_jobs_do_not_use_the_quota(client, db):
    _, uid, h = make_sandbox(client)
    db.add(Job(user_id=uid, kind=JobKind.cv_parse, payload={}, status=JobStatus.failed,
               last_error="LLMPermanentError: demo AI budget reached for today"))  # fmt: skip
    db.commit()
    assert client.post("/profiles/me/cv", data={"text": CV}, headers=h).status_code == 202
    db.add(
        Job(
            user_id=uid,
            kind=JobKind.repo_analyze,
            payload={},
            status=JobStatus.failed,
            last_error="GitHubError: nope",
        )
    )
    db.commit()  # any other failure does count
    assert (
        client.post(
            "/profiles/me/repos", json={"url": "https://github.com/a/b"}, headers=h
        ).status_code
        == 429
    )


def test_rank_quota_and_explains_only_top_five(client, db, factory):
    _, uid, h = make_sandbox(client, "recruiter")
    post = db.scalar(
        select(JobPosting).where(JobPosting.recruiter_id == uid, JobPosting.title.like("%Backend%"))
    )
    for ms in db.scalars(select(MatchScore).where(MatchScore.posting_id == post.id)):
        ms.explained = False  # make every candidate need an LLM call
    db.commit()
    assert client.post(f"/postings/{post.id}/rank", headers=h).status_code == 202
    llm = FakeLLM([review()] * 10)
    drain(factory, llm)
    assert len(llm.calls) == 5  # six candidates, top 5 explained (20 for real recruiters)
    assert client.post(f"/postings/{post.id}/rank", headers=h).status_code == 202
    r = client.post(f"/postings/{post.id}/rank", headers=h)
    assert r.status_code == 429 and r.json()["detail"] == "demo limit reached for this sandbox"


def test_real_users_are_never_limited(db, user_factory):
    u = user_factory("real@example.com")
    for _ in range(6):
        db.add(Job(user_id=u.id, kind=JobKind.cv_parse, payload={}))
    db.commit()
    for kind in quota.LIMITS:
        quota.check(db, u, kind)  # no-op: world_id is NULL


# --- sweep -------------------------------------------------------------------------------------


def test_sweep_deletes_expired_worlds_and_keeps_ledger(client, db, factory, user_factory):
    real = user_factory("real@example.com")
    db.add(Job(user_id=real.id, kind=JobKind.cv_parse, payload={}))
    db.commit()
    baseline = counts(db)
    _, uid, _ = make_sandbox(client)
    _, uid2, _ = make_sandbox(client, "recruiter")
    w = db.get(User, uid).world_id
    day = datetime.now(UTC).date()
    for user_id, world_id, actual in ((uid, w, 0.08), (None, None, None)):
        db.add(
            LlmLedger(day=day, user_id=user_id, world_id=world_id, kind="cv_parse",
                      reserved_usd=0.2, actual_usd=actual)
        )  # fmt: skip
    db.commit()
    with factory() as s:  # not yet expired: nothing happens
        assert sweep_expired(s, now=datetime.now(UTC) + timedelta(hours=1)) == 0
    assert db.scalar(select(func.count()).select_from(User)) == baseline["users"] + 15
    with factory() as s:
        assert sweep_expired(s, now=datetime.now(UTC) + timedelta(hours=25)) == 2
    db.expire_all()
    after = counts(db)
    assert after.pop("llm_ledger") == 2  # spend survives; everything else is back to baseline
    assert after == {k: v for k, v in baseline.items() if k != "llm_ledger"}
    rows = db.scalars(select(LlmLedger)).all()
    assert all(r.world_id is None and r.user_id is None for r in rows)
    assert {r.actual_usd for r in rows} == {0.08, None}  # amounts survive
    assert db.get(User, real.id) is not None


def test_sweep_leaves_every_table_at_baseline(client, db, factory, user_factory):
    user_factory("real@example.com")
    baseline = counts(db)
    for role in ("developer", "recruiter"):
        make_sandbox(client, role)
    assert counts(db) != baseline
    with factory() as s:
        sweep_expired(s, now=datetime.now(UTC) + timedelta(hours=25))
    db.expire_all()
    assert counts(db) == baseline


def test_job_in_flight_when_its_world_is_swept_is_harmless(client, db, factory):
    """Review Focus 4: handlers find their rows gone and no-op; the status update hits 0 rows."""
    _, uid, _ = make_sandbox(client)
    world = db.get(User, uid).world_id
    ids = {
        "cv_document_id": "cv", "repository_id": "repo", "posting_id": "post", "profile_id": uid,
        "assessment_id": "asm", "application_id": "app",
    }  # fmt: skip
    post = db.scalar(
        select(JobPosting)
        .join(User, User.id == JobPosting.recruiter_id)
        .where(User.world_id == world)
    )
    ids["posting_id"] = post.id
    for kind in JobKind:
        db.add(Job(user_id=uid, kind=kind, payload=dict(ids)))
    db.commit()

    def sweeper(d, job, llm):  # the world is deleted by "another process" while this job runs
        with factory() as other:
            sweep_expired(other, now=datetime.now(UTC) + timedelta(hours=25))

    assert run_once(factory, {k: sweeper for k in JobKind}, FakeLLM([])) is True  # no exception
    db.expire_all()
    assert (
        db.scalar(select(func.count()).select_from(Job)) == 0
    )  # every queued job went with the world
    llm = FakeLLM([])  # any LLM call would raise IndexError
    for kind in JobKind:
        with factory() as s:
            HANDLERS[kind](s, Job(user_id=uid, kind=kind, payload=dict(ids)), llm)
    assert llm.calls == []


def test_worker_runs_the_sweep_on_a_timer(monkeypatch, factory):
    import signal

    import firstdev.jobs as jobs

    calls = {"sweep": 0, "run": 0}
    clock = {"t": 1000.0}

    def run(*a, **k):
        calls["run"] += 1
        clock["t"] += 400  # 400 s per iteration: sweeps at the start, then every 10 minutes
        if calls["run"] == 5:
            signal.raise_signal(signal.SIGTERM)
        return True

    monkeypatch.setattr(jobs, "run_once", run)
    monkeypatch.setattr(jobs, "requeue_stale", lambda db: 0)
    monkeypatch.setattr(
        jobs, "sweep_expired", lambda db: calls.__setitem__("sweep", calls["sweep"] + 1)
    )
    monkeypatch.setattr(jobs.time, "monotonic", lambda: clock["t"])
    jobs.worker_main(factory, FakeLLM([]), handlers={})
    # iteration times: 1000 (sweep), 1400, 1800 (sweep), 2200, 2600 (sweep)
    assert calls["sweep"] == 3


def test_sweep_failure_does_not_kill_the_worker(monkeypatch, factory):
    import signal

    import firstdev.jobs as jobs

    def boom(db):
        raise RuntimeError("database is locked")

    def run(*a, **k):
        signal.raise_signal(signal.SIGTERM)
        return True

    monkeypatch.setattr(jobs, "run_once", run)
    monkeypatch.setattr(jobs, "requeue_stale", lambda db: 0)
    monkeypatch.setattr(jobs, "sweep_expired", boom)
    jobs.worker_main(factory, FakeLLM([]), handlers={})  # returns normally


def test_me_reports_sandbox_without_world_id(client, register, login):
    register()
    plain = client.get("/me", headers=login()).json()
    assert plain["sandbox"] is False and plain["expires_at"] is None

    r = client.post("/demo/sandbox", json={"role": "developer", "turnstile_token": "t"})
    assert r.status_code == 201
    me = client.get("/me").json()  # cookie session
    assert me["sandbox"] is True and me["expires_at"] is not None
    assert "world_id" not in me
