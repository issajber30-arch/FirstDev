# Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform.
import pytest
from sqlalchemy import select

from firstdev.models import (
    Application,
    ApplicationStatus,
    ApplicationStatusEvent,
    CvDocument,
    CvStatus,
    Invitation,
    InvitationStatus,
    Job,
    JobKind,
    JobPosting,
    MatchScore,
    PostingStatus,
    RepoAnalysis,
    Repository,
)

BODY = {"title": "Backend dev", "description": "Build APIs", "required_skills": ["python"]}
VERIFY_MSG = "verify your profile first: a parsed CV and an analyzed repository are required"


def verify(db, user_id, cv_status=CvStatus.parsed, analysis=True):
    """Give the developer a CV and (optionally) an analyzed repository."""
    db.add(CvDocument(profile_id=user_id, sha256="0" * 64, size=1, status=cv_status))
    repo = Repository(profile_id=user_id, owner="o", name="n")
    db.add(repo)
    db.flush()
    if analysis:
        db.add(
            RepoAnalysis(
                repository_id=repo.id,
                commit_sha="a" * 40,
                metrics={},
                assessment={},
                tutorial_likelihood=0.0,
                model="m",
            )
        )
    db.commit()


@pytest.fixture
def rec(register, login):
    register("rec@example.com", role="recruiter")
    return login("rec@example.com")


@pytest.fixture
def rec2(register, login):
    register("rec2@example.com", role="recruiter")
    return login("rec2@example.com")


@pytest.fixture
def open_posting(client, rec):
    return client.post("/postings", json={**BODY, "status": "open"}, headers=rec).json()["id"]


@pytest.fixture
def dev(register, login, db):
    me = register("dev@example.com")
    verify(db, me["id"])
    return {"id": me["id"], "h": login("dev@example.com")}


def apply(client, pid, h):
    return client.post(f"/postings/{pid}/apply", headers=h)


def test_unverified_cases_403(client, db, register, login, open_posting):
    cases = {
        "none": None,
        "cv_only": dict(analysis=False),
        "failed_cv": dict(cv_status=CvStatus.failed),
    }
    for name, kw in cases.items():
        me = register(f"{name}@example.com")
        if kw is not None:
            verify(db, me["id"], **kw)
        r = apply(client, open_posting, login(f"{name}@example.com"))
        assert r.status_code == 403 and r.json()["detail"] == VERIFY_MSG, name
    assert db.scalars(select(Application)).all() == []


def test_analysis_without_parsed_cv_403(client, db, register, login, open_posting):
    me = register("a@example.com")
    verify(db, me["id"], cv_status=CvStatus.pending)
    assert apply(client, open_posting, login("a@example.com")).status_code == 403


def test_apply_creates_event_and_score_job(client, db, dev, open_posting):
    r = apply(client, open_posting, dev["h"])
    assert r.status_code == 201, r.text
    b = r.json()
    assert (
        set(b) == {"application_id", "status", "job_id", "assessment_id"}
        and b["status"] == "submitted"
    )
    (ev,) = db.scalars(select(ApplicationStatusEvent)).all()
    assert (ev.from_status, ev.to_status, ev.actor_id) == (
        None,
        ApplicationStatus.submitted,
        dev["id"],
    )
    job = db.get(Job, b["job_id"])
    assert job.kind == JobKind.score_pair
    assert job.payload == {
        "posting_id": open_posting,
        "profile_id": dev["id"],
        "explain": True,
        "application_id": b["application_id"],
    }


def test_duplicate_409_and_closed_or_draft_404(client, dev, rec, open_posting):
    assert apply(client, open_posting, dev["h"]).status_code == 201
    assert apply(client, open_posting, dev["h"]).status_code == 409
    draft = client.post("/postings", json=BODY, headers=rec).json()["id"]
    assert apply(client, draft, dev["h"]).status_code == 404
    client.post(f"/postings/{open_posting}/close", headers=rec)
    assert apply(client, open_posting, dev["h"]).status_code == 404
    assert apply(client, "nope", dev["h"]).status_code == 404


def test_recruiter_and_anonymous_cannot_apply(client, rec, open_posting):
    assert apply(client, open_posting, rec).status_code == 404
    assert client.post(f"/postings/{open_posting}/apply").status_code == 401


def test_daily_limit_429(client, db, dev, user_factory):
    rec = user_factory("r@example.com", role="recruiter")
    ids = []
    for _ in range(11):
        p = JobPosting(recruiter_id=rec.id, title="t", description="d", status=PostingStatus.open)
        db.add(p)
        db.flush()
        ids.append(p.id)
    db.commit()
    for pid in ids[:10]:
        assert apply(client, pid, dev["h"]).status_code == 201
    assert apply(client, ids[10], dev["h"]).status_code == 429


def test_apply_accepts_invitation(client, db, dev, rec, open_posting):
    db.add(
        Invitation(
            posting_id=open_posting,
            profile_id=dev["id"],
            recruiter_id=db.get(JobPosting, open_posting).recruiter_id,
        )
    )
    db.commit()
    assert apply(client, open_posting, dev["h"]).status_code == 201
    db.expire_all()
    assert db.scalars(select(Invitation)).one().status == InvitationStatus.accepted


def test_withdraw(client, db, dev, open_posting, register, login):
    aid = apply(client, open_posting, dev["h"]).json()["application_id"]
    register("other@example.com")
    other = login("other@example.com")
    assert client.post(f"/applications/{aid}/withdraw", headers=other).status_code == 404
    r = client.post(f"/applications/{aid}/withdraw", headers=dev["h"])
    assert r.status_code == 200 and r.json()["status"] == "withdrawn"
    assert client.post(f"/applications/{aid}/withdraw", headers=dev["h"]).status_code == 409
    assert len(db.scalars(select(ApplicationStatusEvent)).all()) == 2


def test_recruiter_status_path_with_events(client, db, dev, rec, open_posting):
    aid = apply(client, open_posting, dev["h"]).json()["application_id"]
    for s in ("reviewing", "interview", "accepted"):
        r = client.post(f"/applications/{aid}/status", json={"status": s}, headers=rec)
        assert r.status_code == 200 and r.json()["status"] == s
    events = db.scalars(select(ApplicationStatusEvent)).all()
    assert len(events) == 4  # submitted + 3 transitions
    assert {e.actor_id for e in events if e.from_status} == {
        db.get(JobPosting, open_posting).recruiter_id
    }


@pytest.mark.parametrize(
    ("frm", "to"),
    [("submitted", "accepted"), ("submitted", "interview"), ("accepted", "rejected")],
)
def test_invalid_transitions_409(client, db, dev, rec, open_posting, frm, to):
    aid = apply(client, open_posting, dev["h"]).json()["application_id"]
    db.get(Application, aid).status = ApplicationStatus(frm)
    db.commit()
    r = client.post(f"/applications/{aid}/status", json={"status": to}, headers=rec)
    assert r.status_code == 409


def test_withdrawn_cannot_change_and_bad_status_422(client, dev, rec, open_posting):
    aid = apply(client, open_posting, dev["h"]).json()["application_id"]
    client.post(f"/applications/{aid}/withdraw", headers=dev["h"])
    r = client.post(f"/applications/{aid}/status", json={"status": "reviewing"}, headers=rec)
    assert r.status_code == 409
    for body in ({"status": "bogus"}, {"status": "reviewing", "x": 1}, {}):
        assert client.post(f"/applications/{aid}/status", json=body, headers=rec).status_code == 422


def test_other_recruiter_and_developer_get_404(client, dev, rec, rec2, open_posting):
    aid = apply(client, open_posting, dev["h"]).json()["application_id"]
    assert client.get(f"/postings/{open_posting}/applications", headers=rec2).status_code == 404
    r = client.post(f"/applications/{aid}/status", json={"status": "reviewing"}, headers=rec2)
    assert r.status_code == 404
    r = client.post(f"/applications/{aid}/status", json={"status": "rejected"}, headers=dev["h"])
    assert r.status_code == 404
    assert client.get(f"/postings/{open_posting}/applications", headers=dev["h"]).status_code == 404


def test_recruiter_list_has_no_feedback_or_pii(client, db, dev, rec, open_posting):
    aid = apply(client, open_posting, dev["h"]).json()["application_id"]
    score = MatchScore(
        posting_id=open_posting,
        profile_id=dev["id"],
        score=80,
        base_score=78.0,
        components={"required_cov": 1.0},
        llm_adjustment=2,
        reasons=["good fit"],
        feedback={"strengths": ["secret feedback"]},
        profile_fingerprint="a",
        posting_fingerprint="b",
        model="m",
        explained=True,
    )
    db.add(score)
    db.flush()
    db.get(Application, aid).match_score_id = score.id
    db.commit()
    r = client.get(f"/postings/{open_posting}/applications", headers=rec)
    assert r.status_code == 200
    (item,) = r.json()
    assert item["score"] == 80 and item["reasons"] == ["good fit"]
    assert item["components"] == {"required_cov": 1.0} and item["injection_flags"] == []
    assert "feedback" not in item and "secret feedback" not in r.text
    assert not {"extracted_text", "email", "education", "contact"} & set(item)
    mine = client.get("/me/applications", headers=dev["h"]).json()
    assert mine[0]["feedback"] == {"strengths": ["secret feedback"]} and mine[0]["score"] == 80


def test_my_applications_scoped_and_unscored(client, dev, rec, open_posting, register, login):
    apply(client, open_posting, dev["h"])
    (item,) = client.get("/me/applications", headers=dev["h"]).json()
    assert item["title"] == "Backend dev" and item["score"] is None and item["feedback"] is None
    register("other@example.com")
    assert client.get("/me/applications", headers=login("other@example.com")).json() == []
    assert client.get("/me/applications", headers=rec).status_code == 404
