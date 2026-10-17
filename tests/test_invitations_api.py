# Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform.
import pytest
from sqlalchemy import select

from firstdev.models import Invitation, InvitationStatus, JobPosting, PostingStatus

BODY = {"title": "Backend dev", "description": "Build APIs", "required_skills": ["python"]}


@pytest.fixture
def rec(register, login):
    register("rec@example.com", role="recruiter")
    return login("rec@example.com")


@pytest.fixture
def open_posting(client, rec):
    return client.post("/postings", json={**BODY, "status": "open"}, headers=rec).json()["id"]


@pytest.fixture
def dev(register, login, client):
    me = register("dev@example.com")
    h = login("dev@example.com")
    client.put("/profiles/me", json={"open_to_opportunities": True}, headers=h)
    return {"id": me["id"], "h": h}


def invite(client, pid, profile_id, h):
    return client.post(f"/postings/{pid}/invite", json={"profile_id": profile_id}, headers=h)


def test_opt_in_toggle(client, dev_headers):
    assert client.get("/profiles/me", headers=dev_headers).json()["open_to_opportunities"] is False
    r = client.put("/profiles/me", json={"open_to_opportunities": True}, headers=dev_headers)
    assert r.json()["open_to_opportunities"] is True
    assert client.get("/profiles/me", headers=dev_headers).json()["open_to_opportunities"] is True
    r = client.put("/profiles/me", json={"open_to_opportunities": "maybe"}, headers=dev_headers)
    assert r.status_code == 422


def test_invite_flow_and_developer_view(client, dev, rec, open_posting):
    r = invite(client, open_posting, dev["id"], rec)
    assert r.status_code == 201 and set(r.json()) == {"invitation_id"}
    (item,) = client.get("/me/invitations", headers=dev["h"]).json()
    assert item["posting_id"] == open_posting and item["title"] == "Backend dev"
    assert item["status"] == "sent" and "created_at" in item
    assert "rec@example.com" not in str(item) and "recruiter_id" not in item


def test_opted_out_and_missing_target_indistinguishable(
    client, rec, open_posting, dev_headers, register
):
    out = register("out@example.com")
    a = invite(client, open_posting, out["id"], rec)
    b = invite(client, open_posting, "00000000-0000-0000-0000-000000000000", rec)
    assert a.status_code == b.status_code == 404 and a.json() == b.json()


def test_recruiter_id_is_not_an_invitable_profile(client, rec, open_posting, register):
    other = register("rec2@example.com", role="recruiter")
    assert invite(client, open_posting, other["id"], rec).status_code == 404


def test_duplicate_409_and_draft_409(client, dev, rec, open_posting):
    assert invite(client, open_posting, dev["id"], rec).status_code == 201
    assert invite(client, open_posting, dev["id"], rec).status_code == 409
    draft = client.post("/postings", json=BODY, headers=rec).json()["id"]
    assert invite(client, draft, dev["id"], rec).status_code == 409


def test_invite_ownership_and_roles(client, dev, rec, open_posting, register, login):
    register("rec2@example.com", role="recruiter")
    assert invite(client, open_posting, dev["id"], login("rec2@example.com")).status_code == 404
    assert invite(client, open_posting, dev["id"], dev["h"]).status_code == 404
    assert (
        client.post(f"/postings/{open_posting}/invite", json={"profile_id": "x"}).status_code == 401
    )
    bad = client.post(
        f"/postings/{open_posting}/invite", json={"profile_id": dev["id"], "x": 1}, headers=rec
    )
    assert bad.status_code == 422


def test_decline(client, db, dev, rec, open_posting, register, login):
    iid = invite(client, open_posting, dev["id"], rec).json()["invitation_id"]
    register("other@example.com")
    other = login("other@example.com")
    assert client.post(f"/invitations/{iid}/decline", headers=other).status_code == 404
    assert client.post(f"/invitations/{iid}/decline", headers=rec).status_code == 404
    r = client.post(f"/invitations/{iid}/decline", headers=dev["h"])
    assert r.status_code == 200 and r.json()["status"] == "declined"
    assert client.post(f"/invitations/{iid}/decline", headers=dev["h"]).status_code == 409
    assert db.scalars(select(Invitation)).one().status == InvitationStatus.declined


def test_daily_invite_limit(client, db, rec, register, open_posting):
    ids = [register(f"d{i}@example.com")["id"] for i in range(21)]
    from firstdev.models import DeveloperProfile

    for i in ids:
        db.get(DeveloperProfile, i).open_to_opportunities = True
    db.commit()
    for i in ids[:20]:
        assert invite(client, open_posting, i, rec).status_code == 201
    assert invite(client, open_posting, ids[20], rec).status_code == 429


def test_my_invitations_only_own_and_developer_only(
    client, dev, rec, open_posting, register, login
):
    invite(client, open_posting, dev["id"], rec)
    register("other@example.com")
    assert client.get("/me/invitations", headers=login("other@example.com")).json() == []
    assert client.get("/me/invitations", headers=rec).status_code == 404
    assert client.get("/me/invitations").status_code == 401


def test_closed_posting_not_invitable(client, dev, rec, open_posting, db):
    db.get(JobPosting, open_posting).status = PostingStatus.closed
    db.commit()
    assert invite(client, open_posting, dev["id"], rec).status_code == 409
