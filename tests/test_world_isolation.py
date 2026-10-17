# Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform.
"""World-leak suite: a real world (R) and two sandbox worlds (A, B) with matching data.

Every cross-user route is called as each world's developer and recruiter against the other
worlds' ids. Foreign ids must answer 404, and no foreign uuid may appear in any response body.
"""

import re
import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy.orm import sessionmaker
from test_matches_api import drain, review, verify

from firstdev import auth
from firstdev.llm import FakeLLM
from firstdev.models import (
    Application,
    DeveloperProfile,
    Invitation,
    Job,
    JobKind,
    JobPosting,
    PostingStatus,
    Role,
    User,
)
from firstdev.pipelines import match_jobs
from firstdev.worlds import in_world, same_world

WORLDS = {"R": None, "A": str(uuid.uuid4()), "B": str(uuid.uuid4())}


def _user(db, email, role, world_id):
    u = User(email=email, password_hash="h", role=role, display_name=email, world_id=world_id)
    db.add(u)
    db.flush()
    if role == Role.developer:
        db.add(DeveloperProfile(user_id=u.id, headline=f"hl {email}", open_to_opportunities=True))
        db.flush()
        verify(db, u.id, ["python"], ["python"])
    return u


def _build(db, name):
    """One recruiter, an open posting, two verified opted-in devs, an application (dev0),
    an invitation (dev1) and match scores, all inside one world."""
    w = WORLDS[name]
    rec = _user(db, f"rec-{name}@x.com", Role.recruiter, w)
    devs = [_user(db, f"dev{i}-{name}@x.com", Role.developer, w) for i in range(2)]
    post = JobPosting(
        recruiter_id=rec.id, title=f"Backend {name}", description="d",
        required_skills=["python"], optional_skills=[], status=PostingStatus.open,
    )  # fmt: skip
    db.add(post)
    db.flush()
    app = Application(job_posting_id=post.id, profile_id=devs[0].id)
    inv = Invitation(posting_id=post.id, profile_id=devs[1].id, recruiter_id=rec.id)
    db.add_all([app, inv])
    db.commit()
    match_jobs._embed_posting(db, post)
    for d in devs:
        job = Job(user_id=d.id, kind=JobKind.embed_profile, payload={"profile_id": d.id})
        match_jobs.handle_embed_profile(db, job, FakeLLM([]))
        match_jobs.score_and_store(
            db, FakeLLM([]), posting=post, profile=db.get(DeveloperProfile, d.id), explain=False
        )
    db.commit()
    ids = {rec.id, post.id, app.id, inv.id, *(d.id for d in devs)}
    return SimpleNamespace(
        name=name, rec=rec, devs=devs, post=post, app=app, inv=inv, ids=ids,
        h={u.id: {"Authorization": f"Bearer {auth.create_token(u.id)}"} for u in (rec, *devs)},
    )  # fmt: skip


@pytest.fixture
def worlds(engine, db, client):
    ws = {n: _build(db, n) for n in WORLDS}
    # Every recruiter ranks their own posting; the pool must stay inside the world.
    for w in ws.values():
        assert client.post(f"/postings/{w.post.id}/rank", headers=w.h[w.rec.id]).status_code == 202
    drain(sessionmaker(engine, expire_on_commit=False), FakeLLM([review()] * 6))
    return ws


def _foreign_ids(worlds, me):
    return {i for n, w in worlds.items() if n != me for i in w.ids}


def _no_leak(resp, foreign):
    text = resp.text
    assert not [i for i in foreign if re.search(re.escape(i), text)], text


CALLERS = [(n, who) for n in WORLDS for who in ("dev", "rec")]


def _caller(worlds, name, who):
    w = worlds[name]
    return w, (w.h[w.devs[1].id] if who == "dev" else w.h[w.rec.id])


@pytest.mark.parametrize(("name", "who"), CALLERS)
def test_posting_read_is_world_scoped(client, worlds, name, who):
    w, h = _caller(worlds, name, who)
    foreign = _foreign_ids(worlds, name)
    assert client.get(f"/postings/{w.post.id}", headers=h).status_code == 200
    for other in worlds.values():
        if other is not w:
            r = client.get(f"/postings/{other.post.id}", headers=h)
            assert r.status_code == 404 and r.json() == {"detail": "not found"}
    r = client.get(f"/postings/{uuid.uuid4()}", headers=h)  # identical to a real foreign id
    assert r.status_code == 404 and r.json() == {"detail": "not found"}
    _no_leak(client.get(f"/postings/{w.post.id}", headers=h), foreign)


@pytest.mark.parametrize("name", list(WORLDS))
def test_developer_cross_world_routes_are_404(client, worlds, name):
    w, h = _caller(worlds, name, "dev")
    foreign = _foreign_ids(worlds, name)
    for other in (o for o in worlds.values() if o is not w):
        for r in (
            client.post(f"/postings/{other.post.id}/apply", headers=h),
            client.get(f"/me/matches/{other.post.id}", headers=h),
            client.post(f"/applications/{other.app.id}/withdraw", headers=h),
            client.post(f"/invitations/{other.inv.id}/decline", headers=h),
            client.get(f"/applications/{other.app.id}/assessment", headers=h),
        ):
            assert r.status_code == 404, (r.request.url, r.text)
            _no_leak(r, foreign)
    # control: the same call on the own world's posting is accepted
    assert client.post(f"/postings/{w.post.id}/apply", headers=h).status_code == 201


@pytest.mark.parametrize("name", list(WORLDS))
def test_developer_lists_stay_in_world(client, worlds, name):
    w, h = _caller(worlds, name, "dev")
    foreign = _foreign_ids(worlds, name)
    rec = client.get("/me/recommended-jobs", headers=h)
    assert rec.status_code == 200
    assert [j["posting_id"] for j in rec.json()["jobs"]] == [w.post.id]
    _no_leak(rec, foreign)
    for path in (
        "/me/applications", "/me/invitations", "/me/assessments", "/me/connections",
        "/me/connection-requests",
    ):  # fmt: skip
        r = client.get(path, headers=h)
        assert r.status_code == 200
        _no_leak(r, foreign)
    assert [i["posting_id"] for i in client.get("/me/invitations", headers=h).json()] == [w.post.id]


@pytest.mark.parametrize("name", list(WORLDS))
def test_recruiter_cross_world_routes_are_404(client, worlds, name):
    w, h = _caller(worlds, name, "rec")
    foreign = _foreign_ids(worlds, name)
    for other in (o for o in worlds.values() if o is not w):
        calls = [
            client.post(f"/postings/{other.post.id}/rank", headers=h),
            client.get(f"/postings/{other.post.id}/candidates", headers=h),
            client.get(f"/postings/{other.post.id}/applications", headers=h),
            client.put(
                f"/postings/{other.post.id}",
                json={"title": "x", "description": "y", "required_skills": ["python"]},
                headers=h,
            ),
            client.post(f"/postings/{other.post.id}/close", headers=h),
            client.post(f"/postings/{other.post.id}/invite", json={"profile_id": "x"}, headers=h),
            client.post(f"/applications/{other.app.id}/status", json={"status": "reviewing"},
                        headers=h),
            client.post(f"/applications/{other.app.id}/assessment", headers=h),
            client.get(f"/applications/{other.app.id}/assessment", headers=h),
        ]  # fmt: skip
        for r in calls:
            assert r.status_code == 404, (r.request.url, r.text)
            _no_leak(r, foreign)


@pytest.mark.parametrize("name", list(WORLDS))
def test_invite_target_must_share_the_world(client, worlds, name):
    w, h = _caller(worlds, name, "rec")
    for other in (o for o in worlds.values() if o is not w):
        for d in other.devs:
            r = client.post(f"/postings/{w.post.id}/invite", json={"profile_id": d.id}, headers=h)
            assert r.status_code == 404 and r.json() == {"detail": "not found"}
    # control: an own-world developer can be invited
    r = client.post(f"/postings/{w.post.id}/invite", json={"profile_id": w.devs[0].id}, headers=h)
    assert r.status_code == 201


@pytest.mark.parametrize("name", list(WORLDS))
def test_ranking_pool_and_candidates_stay_in_world(client, worlds, name):
    w, h = _caller(worlds, name, "rec")
    r = client.get(f"/postings/{w.post.id}/candidates", headers=h)
    assert r.status_code == 200
    assert {c["profile_id"] for c in r.json()} == {d.id for d in w.devs}
    _no_leak(r, _foreign_ids(worlds, name))
    apps = client.get(f"/postings/{w.post.id}/applications", headers=h)
    assert [a["profile_id"] for a in apps.json()] == [w.devs[0].id]
    _no_leak(apps, _foreign_ids(worlds, name))


def test_corrupt_cross_world_rows_stay_hidden(client, db, engine, worlds):
    """Defence in depth: even if a foreign application/score got into a world, it never shows."""
    a, b = worlds["A"], worlds["B"]
    stray = Application(job_posting_id=a.post.id, profile_id=b.devs[0].id)
    db.add(stray)
    db.commit()
    h = a.h[a.rec.id]
    assert client.post(f"/applications/{stray.id}/status", json={"status": "reviewing"},
                       headers=h).status_code == 404  # fmt: skip
    r = client.get(f"/postings/{a.post.id}/applications", headers=h)
    assert stray.id not in r.text and b.devs[0].id not in r.text
    # the worker refuses a cross-world pair even if one were enqueued
    payload = {"posting_id": a.post.id, "profile_id": b.devs[1].id, "explain": False}
    job = Job(user_id=a.rec.id, kind=JobKind.score_pair, payload=payload)
    db.add(job)
    db.commit()
    match_jobs.handle_score_pair(db, job, FakeLLM([]))
    assert client.get(f"/postings/{a.post.id}/candidates", headers=h).text.count(b.devs[1].id) == 0


def test_same_world_helpers(db, worlds):
    from sqlalchemy import select

    a, r = worlds["A"], worlds["R"]
    assert in_world(db, a.devs[0].id, a.rec) and not in_world(db, a.devs[0].id, r.rec)
    assert in_world(db, r.devs[0].id, r.rec) and not in_world(db, r.devs[0].id, a.rec)
    ids = set(db.scalars(same_world(select(User.id), User.id, a.rec)))
    assert ids == {a.rec.id, *(d.id for d in a.devs)}
    real = set(db.scalars(same_world(select(User.id), User.id, r.devs[0])))
    assert real == {r.rec.id, *(d.id for d in r.devs)}


@pytest.mark.parametrize(("name", "who"), CALLERS)
def test_connections_are_world_scoped(client, db, worlds, name, who):
    from firstdev.models import Connection

    w, h = _caller(worlds, name, who)
    me = w.devs[1] if who == "dev" else w.rec
    foreign = _foreign_ids(worlds, name)
    for other in (o for o in worlds.values() if o is not w):
        for u in (other.rec, *other.devs):
            r = client.post("/connections", json={"user_id": u.id}, headers=h)
            assert r.status_code == 404 and r.json() == {"detail": "not found"}
    # control: an own-world user can be asked, and the lists then show only own-world ids
    mate = w.devs[0] if who == "dev" else w.devs[1]
    cid = client.post("/connections", json={"user_id": mate.id}, headers=h)
    assert cid.status_code == 201
    # a forged cross-world row (should never exist) is invisible and unactionable
    other = next(o for o in worlds.values() if o is not w)
    stray = Connection(requester_id=other.rec.id, addressee_id=me.id)
    db.add(stray)
    db.commit()
    assert client.post(f"/connections/{stray.id}/accept", headers=h).status_code == 404
    assert client.delete(f"/connections/{stray.id}", headers=h).status_code == 404
    for path in ("/me/connections", "/me/connection-requests"):
        r = client.get(path, headers=h)
        assert r.status_code == 200
        _no_leak(r, foreign)
        assert stray.id not in r.text
