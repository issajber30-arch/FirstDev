# Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform.
import uuid

import pytest
from conftest import PASSWORD
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from firstdev.auth import get_owned
from firstdev.models import (
    Application,
    Connection,
    CvDocument,
    DeveloperProfile,
    Job,
    JobPosting,
    Repository,
    Role,
    User,
)


def _user(db, email, role=Role.developer, profile=True):
    u = User(email=email, password_hash="h", role=role)
    db.add(u)
    db.flush()
    if profile:
        db.add(DeveloperProfile(user_id=u.id))
    db.commit()
    return u


def _posting(db, rec, **kw):
    p = JobPosting(recruiter_id=rec.id, title="t", description="d", **kw)
    db.add(p)
    db.commit()
    return p


def test_ids_are_uuid4_strings(db):
    u = _user(db, "a@example.com")
    assert uuid.UUID(u.id).version == 4 and len(u.id) == 36


def test_created_at_set(db):
    assert _user(db, "a@example.com").created_at is not None


def test_get_owned_idor_returns_404(db):
    a, b = _user(db, "a@example.com"), _user(db, "b@example.com")
    repo = Repository(profile_id=a.id, owner="o", name="n")
    db.add(repo)
    db.commit()
    assert get_owned(db, Repository, repo.id, a).id == repo.id
    for uid, user in ((repo.id, b), (str(uuid.uuid4()), a), ("not-a-uuid", a)):
        with pytest.raises(HTTPException) as e:
            get_owned(db, Repository, uid, user)
        assert e.value.status_code == 404


def test_get_owned_other_owner_columns(db):
    a, b = _user(db, "a@example.com"), _user(db, "b@example.com")
    job = Job(user_id=a.id, kind="cv_parse", payload={})
    db.add(job)
    db.commit()
    assert get_owned(db, Job, job.id, a).id == job.id
    with pytest.raises(HTTPException):
        get_owned(db, Job, job.id, b)


def test_self_connection_rejected(db):
    a = _user(db, "a@example.com")
    db.add(Connection(requester_id=a.id, addressee_id=a.id))
    with pytest.raises(IntegrityError):
        db.commit()


def test_duplicate_connection_rejected(db):
    a, b = _user(db, "a@example.com"), _user(db, "b@example.com")
    db.add(Connection(requester_id=a.id, addressee_id=b.id))
    db.commit()
    db.add(Connection(requester_id=a.id, addressee_id=b.id))
    with pytest.raises(IntegrityError):
        db.commit()


def test_duplicate_repository_rejected(db):
    a = _user(db, "a@example.com")
    db.add(Repository(profile_id=a.id, owner="o", name="n"))
    db.commit()
    db.add(Repository(profile_id=a.id, owner="o", name="n"))
    with pytest.raises(IntegrityError):
        db.commit()


@pytest.mark.parametrize(
    ("lo", "hi", "ok"),
    [
        (100, 50, False),
        (-1, 5, False),
        (5, -1, False),
        (50, 50, True),
        (None, 5, True),
        (5, None, True),
    ],
)
def test_salary_constraints(db, lo, hi, ok):
    rec = _user(db, "r@example.com", Role.recruiter, profile=False)
    if ok:
        _posting(db, rec, salary_min=lo, salary_max=hi)
    else:
        with pytest.raises(IntegrityError):
            _posting(db, rec, salary_min=lo, salary_max=hi)


def test_duplicate_application_rejected(db):
    rec = _user(db, "r@example.com", Role.recruiter, profile=False)
    dev = _user(db, "d@example.com")
    posting = _posting(db, rec)
    db.add(Application(job_posting_id=posting.id, profile_id=dev.id))
    db.commit()
    db.add(Application(job_posting_id=posting.id, profile_id=dev.id))
    with pytest.raises(IntegrityError):
        db.commit()


def test_invalid_enum_value_rejected_by_db(engine):
    with engine.begin() as c, pytest.raises(IntegrityError):
        c.exec_driver_sql(
            "INSERT INTO users (id, email, password_hash, role, created_at) "
            "VALUES ('1', 'x@y.z', 'h', 'superuser', '2026-01-01')"
        )


def test_delete_me_wrong_password(client, db, register, login):
    register()
    h = login()
    for pw in ("wrong", ""):
        r = client.request("DELETE", "/me", json={"password": pw}, headers=h)
        assert r.status_code == 403
    assert client.get("/me", headers=h).status_code == 200
    assert client.request("DELETE", "/me", json={}, headers=h).status_code == 422
    assert client.request("DELETE", "/me", headers=h).status_code == 422
    assert client.request("DELETE", "/me", json={"password": PASSWORD}).status_code == 401


def test_delete_me_cascades_everything(client, db, register, login):
    me = register("me@example.com")
    other = register("other@example.com")
    rec = register("rec@example.com", role="recruiter")
    h = login("me@example.com")
    posting = _posting(db, db.get(User, rec["id"]))
    db.add_all(
        [
            Repository(profile_id=me["id"], owner="o", name="n"),
            CvDocument(profile_id=me["id"], sha256="0" * 64, size=1),
            Connection(requester_id=me["id"], addressee_id=other["id"]),
            Connection(requester_id=other["id"], addressee_id=me["id"]),
            Job(user_id=me["id"], kind="cv_parse", payload={}),
            Application(job_posting_id=posting.id, profile_id=me["id"]),
            Repository(profile_id=other["id"], owner="o", name="keep"),
        ]
    )
    db.commit()

    assert (
        client.request("DELETE", "/me", json={"password": PASSWORD}, headers=h).status_code == 204
    )

    db.expire_all()
    assert db.get(User, me["id"]) is None
    assert db.get(DeveloperProfile, me["id"]) is None
    for model in (CvDocument, Connection, Job):
        assert db.scalars(select(model)).all() == [], model.__name__
    assert db.scalars(select(Application)).all() == []
    assert [r.name for r in db.scalars(select(Repository))] == ["keep"]
    assert db.get(User, other["id"]) is not None and db.get(JobPosting, posting.id) is not None
    assert client.get("/me", headers=h).status_code == 401


def test_delete_recruiter_cascades_postings(client, db, register, login):
    rec = register("rec@example.com", role="recruiter")
    _posting(db, db.get(User, rec["id"]))
    r = client.request(
        "DELETE", "/me", json={"password": PASSWORD}, headers=login("rec@example.com")
    )
    assert r.status_code == 204
    assert db.scalars(select(JobPosting)).all() == []


def test_datetimes_come_back_aware_utc(db):

    user = User(email="tz@example.com", password_hash="x", role="developer")
    db.add(user)
    db.commit()
    db.expire_all()
    loaded = db.get(User, user.id)
    assert loaded.created_at.tzinfo is not None
    assert loaded.created_at.utcoffset().total_seconds() == 0


def test_naive_datetime_rejected(db):
    from datetime import datetime

    import pytest
    from sqlalchemy.exc import StatementError

    db.add(
        User(
            email="naive@example.com",
            password_hash="x",
            role="developer",
            created_at=datetime(2026, 1, 1),
        )
    )
    with pytest.raises(StatementError):
        db.commit()
