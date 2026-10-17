# Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform.
"""Assessment triggers: recruiter send, auto on apply, practice, own list, cost guard."""

from datetime import UTC, datetime, timedelta

import pytest
from assess_helpers import apply_to, seed
from sqlalchemy import select
from test_applications_api import BODY, VERIFY_MSG, apply, verify

from firstdev.llm import FakeLLM, get_llm
from firstdev.models import (
    Application,
    ApplicationStatus,
    Assessment,
    AssessmentKind,
    AssessmentStatus,
    DeveloperProfile,
    Job,
    JobKind,
    JobPosting,
)


@pytest.fixture(autouse=True)
def llm(client):
    """Cost guard: an empty queue makes any in-request LLM call fail the test."""
    fake = FakeLLM([])
    client.app.dependency_overrides[get_llm] = lambda: fake
    yield fake
    assert fake.calls == []


@pytest.fixture
def rec(register, login):
    register("rec@example.com", role="recruiter")
    return login("rec@example.com")


@pytest.fixture
def dev(register, login, db):
    me = register("dev@example.com")
    verify(db, me["id"])
    return {"id": me["id"], "h": login("dev@example.com")}


def mk_posting(client, rec, **kw):
    r = client.post("/postings", json={**BODY, "status": "open", **kw}, headers=rec)
    assert r.status_code == 201, r.text
    return r.json()


@pytest.fixture
def posting_id(client, rec):
    return mk_posting(client, rec)["id"]


@pytest.fixture
def app_id(client, dev, posting_id):
    return apply(client, posting_id, dev["h"]).json()["application_id"]


def send(client, app_id, h):
    return client.post(f"/applications/{app_id}/assessment", headers=h)


def practice(client, h, skills):
    return client.post("/me/assessments", json={"skills": skills}, headers=h)


# --- recruiter send ----------------------------------------------------------------------------


def test_send_queues_generation(client, db, rec, app_id):
    r = send(client, app_id, rec)
    assert r.status_code == 202 and r.json()["status"] == "generating"
    a = db.get(Assessment, r.json()["assessment_id"])
    assert (a.kind, a.application_id) == (AssessmentKind.recruiter, app_id)
    jobs = db.scalars(select(Job).where(Job.kind == JobKind.assessment_generate)).all()
    assert [j.payload for j in jobs] == [{"assessment_id": a.id}]


def test_send_twice_409(client, rec, app_id):
    assert send(client, app_id, rec).status_code == 202
    assert send(client, app_id, rec).status_code == 409


@pytest.mark.parametrize("status", [ApplicationStatus.withdrawn, ApplicationStatus.rejected])
def test_send_for_closed_application_409(client, db, rec, app_id, status):
    db.get(Application, app_id).status = status
    db.commit()
    assert send(client, app_id, rec).status_code == 409


def test_send_other_recruiter_or_developer_404(client, register, login, rec, dev, app_id):
    register("rec2@example.com", role="recruiter")
    assert send(client, app_id, login("rec2@example.com")).status_code == 404
    assert send(client, app_id, dev["h"]).status_code == 404
    assert send(client, "nope", rec).status_code == 404


def test_send_21st_is_429(client, db, rec, dev, register, posting_id):
    rec_id = db.get(JobPosting, posting_id).recruiter_id
    for i in range(20):  # 20 recent sends by this recruiter, seeded directly
        me = register(f"d{i}@example.com")
        p = db.get(DeveloperProfile, me["id"])
        post = db.get(JobPosting, posting_id)
        seed(db, p, kind=AssessmentKind.recruiter, status=AssessmentStatus.generating,
             posting=post, application=apply_to(db, p, post), created_by=rec_id)  # fmt: skip
    app_id = apply(client, posting_id, dev["h"]).json()["application_id"]
    assert send(client, app_id, rec).status_code == 429


# --- auto assessment ---------------------------------------------------------------------------


def test_auto_off_apply_creates_nothing(client, db, dev, posting_id):
    r = apply(client, posting_id, dev["h"])
    assert r.status_code == 201 and r.json()["assessment_id"] is None
    assert db.scalars(select(Assessment)).all() == []


def test_auto_on_apply_creates_auto_assessment(client, db, rec, dev):
    pid = mk_posting(client, rec, auto_assessment=True)["id"]
    r = apply(client, pid, dev["h"])
    assert r.status_code == 201, r.text
    a = db.get(Assessment, r.json()["assessment_id"])
    assert (a.kind, a.created_by, a.application_id) == (
        AssessmentKind.auto, None, r.json()["application_id"],
    )  # fmt: skip
    kinds = {j.kind for j in db.scalars(select(Job))}
    assert {JobKind.assessment_generate, JobKind.score_pair} <= kinds


def test_auto_assessment_is_owner_only(client, rec, dev):
    p = mk_posting(client, rec, auto_assessment=True)
    assert p["auto_assessment"] is True
    assert client.get(f"/postings/{p['id']}", headers=rec).json()["auto_assessment"] is True
    assert client.get("/postings/mine", headers=rec).json()[0]["auto_assessment"] is True
    assert client.get(f"/postings/{p['id']}", headers=dev["h"]).json()["auto_assessment"] is None


# --- practice ----------------------------------------------------------------------------------


def test_practice_requires_verified_profile(client, register, login):
    register("new@example.com")
    r = practice(client, login("new@example.com"), ["python"])
    assert r.status_code == 403 and r.json()["detail"] == VERIFY_MSG


def test_practice_recruiter_404(client, rec):
    assert practice(client, rec, ["python"]).status_code == 404


@pytest.mark.parametrize("skills", [[], ["a", "b", "c", "d"]])
def test_practice_skill_count_422(client, dev, skills):
    assert practice(client, dev["h"], skills).status_code == 422


def test_practice_unusable_skills_422_and_extra_forbidden(client, dev):
    assert practice(client, dev["h"], ["  "]).status_code == 422
    r = client.post("/me/assessments", json={"skills": ["python"], "x": 1}, headers=dev["h"])
    assert r.status_code == 422


def test_practice_one_to_three_skills_ok(client, db, dev):
    r = practice(client, dev["h"], ["Python", "sql", "go"])
    assert r.status_code == 202, r.text
    a = db.get(Assessment, r.json()["assessment_id"])
    assert a.kind == AssessmentKind.practice and a.skills == ["go", "python", "sql"]


def test_practice_4th_in_a_day_429(client, dev):
    for s in ("python", "sql", "go"):
        assert practice(client, dev["h"], [s]).status_code == 202
    assert practice(client, dev["h"], ["rust"]).status_code == 429


def test_practice_same_skill_within_7_days_409(client, dev):
    assert practice(client, dev["h"], ["python"]).status_code == 202
    r = practice(client, dev["h"], ["Python", "sql"])
    assert r.status_code == 409 and "python" in r.json()["detail"]


def test_practice_cooldown_ignores_failed_and_old(client, db, dev):
    a = db.get(Assessment, practice(client, dev["h"], ["python"]).json()["assessment_id"])
    a.status = AssessmentStatus.failed
    db.commit()
    assert practice(client, dev["h"], ["python"]).status_code == 202  # retry after failure
    old = db.get(Assessment, practice(client, dev["h"], ["sql"]).json()["assessment_id"])
    old.created_at = datetime.now(UTC) - timedelta(days=8)
    db.commit()
    assert practice(client, dev["h"], ["sql"]).status_code == 202


def test_practice_cooldown_counts_expired(client, db, dev):
    a = db.get(Assessment, practice(client, dev["h"], ["python"]).json()["assessment_id"])
    a.status = AssessmentStatus.expired
    db.commit()
    assert practice(client, dev["h"], ["python"]).status_code == 409


# --- own list ----------------------------------------------------------------------------------


def test_my_assessments_lists_only_own(client, db, register, login, rec, dev, app_id):
    other = register("other@example.com")
    verify(db, other["id"])
    assert practice(client, login("other@example.com"), ["go"]).status_code == 202
    assert practice(client, dev["h"], ["python"]).status_code == 202
    assert send(client, app_id, rec).status_code == 202  # recruiter-sent is the candidate's too
    rows = client.get("/me/assessments", headers=dev["h"]).json()
    assert {r["kind"] for r in rows} == {"practice", "recruiter"} and len(rows) == 2
    assert set(rows[0]) == {"id", "kind", "status", "skills", "overall_pct", "created_at"}
    assert client.get("/me/assessments", headers=rec).status_code == 404
