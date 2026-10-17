# Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform.
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from firstdev import auth
from firstdev.api import connections
from firstdev.models import Connection, ConnectionStatus, DeveloperProfile, Role, User

S = ConnectionStatus
GENERIC = {"detail": connections.UNAVAILABLE}
ITEM_KEYS = {"connection_id", "user_id", "display_name", "handle", "headline"}
PENDING_KEYS = ITEM_KEYS | {"created_at"}


def mk(db, name, role=Role.developer, world=None, handle=None):
    u = User(email=f"{name}@x.com", password_hash="h", role=role, display_name=name.title(),
             world_id=world, handle=handle)  # fmt: skip
    db.add(u)
    db.flush()
    if role == Role.developer:
        db.add(DeveloperProfile(user_id=u.id, headline=f"{name} headline"))
    db.commit()
    return u


def hd(u):
    return {"Authorization": f"Bearer {auth.create_token(u.id)}"}


@pytest.fixture
def trio(db):
    return mk(db, "ann", handle="ann"), mk(db, "bob"), mk(db, "cat")


def ask(client, frm, to):
    return client.post("/connections", json={"user_id": to.id}, headers=hd(frm))


def row(db, cid):
    db.expire_all()
    return db.get(Connection, cid)


def test_request_accept_flow(client, db, trio):
    ann, bob, _ = trio
    r = ask(client, ann, bob)
    assert r.status_code == 201 and r.json()["status"] == "pending"
    cid = r.json()["connection_id"]
    assert row(db, cid).responded_at is None
    r = client.post(f"/connections/{cid}/accept", headers=hd(bob))
    assert r.status_code == 200 and r.json() == {"connection_id": cid, "status": "accepted"}
    assert row(db, cid).status == S.accepted and row(db, cid).responded_at is not None


def test_decline_sets_status_and_time(client, db, trio):
    ann, bob, _ = trio
    cid = ask(client, ann, bob).json()["connection_id"]
    assert (
        client.post(f"/connections/{cid}/decline", headers=hd(bob)).json()["status"] == "declined"
    )
    assert row(db, cid).responded_at is not None


def test_remove_by_either_party(client, db, trio):
    ann, bob, _ = trio
    # accepted pair: either side can remove
    a = ask(client, ann, bob).json()["connection_id"]
    client.post(f"/connections/{a}/accept", headers=hd(bob))
    assert client.delete(f"/connections/{a}", headers=hd(bob)).status_code == 204
    assert row(db, a).status == S.removed and row(db, a).responded_at is not None
    b = ask(client, ann, bob).json()["connection_id"]  # removed pairs may reconnect at once
    client.post(f"/connections/{b}/accept", headers=hd(bob))
    assert client.delete(f"/connections/{b}", headers=hd(ann)).status_code == 204


def test_requester_can_cancel_pending_but_addressee_must_decline(client, db, trio):
    ann, bob, _ = trio
    cid = ask(client, ann, bob).json()["connection_id"]
    assert client.delete(f"/connections/{cid}", headers=hd(bob)).status_code == 404
    assert client.delete(f"/connections/{cid}", headers=hd(ann)).status_code == 204
    assert row(db, cid).status == S.removed


def test_self_is_422_and_unknown_is_404(client, trio):
    ann, _, _ = trio
    assert ask(client, ann, ann).status_code == 422
    r = client.post("/connections", json={"user_id": str(uuid.uuid4())}, headers=hd(ann))
    assert r.status_code == 404
    assert client.post("/connections", json={"user_id": "x"}, headers=hd(ann)).status_code == 404
    assert client.post("/connections", json={}, headers=hd(ann)).status_code == 422
    assert (
        client.post("/connections", json={"user_id": "a" * 37}, headers=hd(ann)).status_code == 422
    )
    assert (
        client.post("/connections", json={"user_id": "x", "extra": 1}, headers=hd(ann)).status_code
        == 422
    )


def test_requires_auth(client):
    assert client.post("/connections", json={"user_id": "x"}).status_code == 401
    assert client.get("/me/connections").status_code == 401
    assert client.get("/me/connection-requests").status_code == 401


def test_recruiter_and_developer_can_connect(client, db):
    rec, dev = mk(db, "rec", Role.recruiter), mk(db, "dev")
    assert ask(client, rec, dev).status_code == 201


def test_duplicates_in_either_direction_are_409(client, trio):
    ann, bob, _ = trio
    cid = ask(client, ann, bob).json()["connection_id"]
    for a, b in ((ann, bob), (bob, ann)):  # pending
        r = ask(client, a, b)
        assert r.status_code == 409 and r.json() == GENERIC
    client.post(f"/connections/{cid}/accept", headers=hd(bob))
    for a, b in ((ann, bob), (bob, ann)):  # accepted
        r = ask(client, a, b)
        assert r.status_code == 409 and r.json() == GENERIC


@pytest.mark.parametrize("reverse", [False, True])
def test_decline_cooldown_blocks_both_directions_with_the_same_message(client, db, trio, reverse):
    ann, bob, _ = trio
    cid = ask(client, ann, bob).json()["connection_id"]
    client.post(f"/connections/{cid}/decline", headers=hd(bob))
    a, b = (bob, ann) if reverse else (ann, bob)
    dup = ask(client, ann, trio[2])  # control for a normal other request
    assert dup.status_code == 201
    r = ask(client, a, b)
    assert r.status_code == 409 and r.json() == GENERIC  # not "declined": requester learns nothing


@pytest.mark.parametrize("reverse", [False, True])
def test_after_30_days_a_new_request_is_allowed(client, db, trio, reverse):
    ann, bob, _ = trio
    cid = ask(client, ann, bob).json()["connection_id"]
    client.post(f"/connections/{cid}/decline", headers=hd(bob))
    c = row(db, cid)
    c.responded_at = datetime.now(UTC) - timedelta(days=29, hours=23)
    db.commit()
    a, b = (bob, ann) if reverse else (ann, bob)
    assert ask(client, a, b).status_code == 409
    c.responded_at = datetime.now(UTC) - timedelta(days=30, seconds=5)
    db.commit()
    r = ask(client, a, b)
    assert r.status_code == 201 and r.json()["status"] == "pending"
    # a pending request must not be duplicated afterwards
    assert ask(client, a, b).status_code == 409
    assert db.scalar(select(Connection).where(Connection.id == r.json()["connection_id"]))


def test_cooldown_logic_takes_now(db, trio):
    ann, bob, _ = trio
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    c = connections.create_request(db, ann, bob.id, now=t0)
    connections.respond(db, c.id, bob, accept=False, now=t0)
    with pytest.raises(HTTPException) as e:
        connections.create_request(db, bob, ann.id, now=t0 + timedelta(days=29, hours=23))
    assert e.value.status_code == 409 and e.value.detail == connections.UNAVAILABLE
    again = connections.create_request(db, ann, bob.id, now=t0 + timedelta(days=30))
    assert again.id == c.id and again.status == S.pending and again.responded_at is None


def test_other_world_is_404(client, db, trio):
    ann, _, _ = trio
    sandbox = mk(db, "sbx", world=str(uuid.uuid4()))
    r = ask(client, ann, sandbox)
    assert (
        r.status_code == 404
        and r.json() == ask(client, ann, ann.__class__(id=str(uuid.uuid4()))).json()
    )
    assert ask(client, sandbox, ann).status_code == 404
    other = mk(db, "sb2", world=str(uuid.uuid4()))
    assert ask(client, sandbox, other).status_code == 404
    mate = mk(db, "mate", world=sandbox.world_id)
    assert ask(client, sandbox, mate).status_code == 201  # same sandbox world is fine


def test_third_parties_and_wrong_side_get_404(client, db, trio):
    ann, bob, cat = trio
    cid = ask(client, ann, bob).json()["connection_id"]
    for who in (cat, ann):  # a stranger, and the requester accepting their own request
        assert client.post(f"/connections/{cid}/accept", headers=hd(who)).status_code == 404
        assert client.post(f"/connections/{cid}/decline", headers=hd(who)).status_code == 404
    assert client.delete(f"/connections/{cid}", headers=hd(cat)).status_code == 404
    assert client.post(f"/connections/{uuid.uuid4()}/accept", headers=hd(bob)).status_code == 404
    assert row(db, cid).status == S.pending


def test_cross_world_connection_row_is_unreachable(client, db, trio):
    ann, _, _ = trio
    sandbox = mk(db, "sbx", world=str(uuid.uuid4()))
    c = Connection(requester_id=sandbox.id, addressee_id=ann.id)  # should never exist
    db.add(c)
    db.commit()
    assert client.post(f"/connections/{c.id}/accept", headers=hd(ann)).status_code == 404
    assert client.get("/me/connection-requests", headers=hd(ann)).json() == {
        "incoming": [], "outgoing": []
    }  # fmt: skip


def test_decline_and_remove_unknown_state_is_404_not_a_leak(client, db, trio):
    ann, bob, _ = trio
    cid = ask(client, ann, bob).json()["connection_id"]
    client.post(f"/connections/{cid}/decline", headers=hd(bob))
    assert client.delete(f"/connections/{cid}", headers=hd(ann)).status_code == 404  # requester
    assert client.post(f"/connections/{cid}/accept", headers=hd(bob)).status_code == 409


def test_51st_request_in_a_day_is_429(client, db, trio):
    ann, _, _ = trio
    targets = [mk(db, f"t{i}") for i in range(51)]
    assert all(ask(client, ann, t).status_code == 201 for t in targets[:50])
    r = ask(client, ann, targets[50])
    assert r.status_code == 429
    # requests older than 24h stop counting
    for c in db.scalars(select(Connection)):
        c.created_at = datetime.now(UTC) - timedelta(hours=25)
    db.commit()
    assert ask(client, ann, targets[50]).status_code == 201


def test_lists_show_only_the_allowlist(client, db, trio):
    ann, bob, cat = trio
    rec = mk(db, "rec", Role.recruiter)
    c1 = ask(client, bob, ann).json()["connection_id"]
    client.post(f"/connections/{c1}/accept", headers=hd(ann))
    c2 = ask(client, rec, ann).json()["connection_id"]
    c3 = ask(client, ann, cat).json()["connection_id"]
    r = client.get("/me/connections", headers=hd(ann))
    assert r.status_code == 200
    (item,) = r.json()
    assert set(item) == ITEM_KEYS
    assert item == {"connection_id": c1, "user_id": bob.id, "display_name": "Bob",
                    "handle": None, "headline": "bob headline"}  # fmt: skip
    reqs = client.get("/me/connection-requests", headers=hd(ann)).json()
    assert set(reqs) == {"incoming", "outgoing"}
    (inc,), (out,) = reqs["incoming"], reqs["outgoing"]
    assert set(inc) == set(out) == PENDING_KEYS
    assert inc["connection_id"] == c2 and inc["headline"] is None  # recruiters have no headline
    assert out["connection_id"] == c3 and out["user_id"] == cat.id
    assert "x.com" not in r.text + str(reqs)  # no email
    # the other side sees the accepted connection too, with ann's handle
    (mine,) = client.get("/me/connections", headers=hd(bob)).json()
    assert mine["user_id"] == ann.id and mine["handle"] == "ann"


def test_declined_and_removed_leave_the_lists(client, db, trio):
    ann, bob, cat = trio
    c1 = ask(client, ann, bob).json()["connection_id"]
    c2 = ask(client, ann, cat).json()["connection_id"]
    client.post(f"/connections/{c1}/decline", headers=hd(bob))
    client.delete(f"/connections/{c2}", headers=hd(ann))
    assert client.get("/me/connection-requests", headers=hd(ann)).json() == {
        "incoming": [], "outgoing": []
    }  # fmt: skip
    assert client.get("/me/connections", headers=hd(ann)).json() == []
