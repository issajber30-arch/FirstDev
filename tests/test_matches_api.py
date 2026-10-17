# Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform.
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from firstdev.jobs import HANDLERS, enqueue, enqueue_embed_profile, run_once
from firstdev.llm import FakeLLM, get_llm
from firstdev.matching.explain import Feedback, MatchReview
from firstdev.models import (
    CvDocument,
    CvParse,
    CvStatus,
    DeveloperProfile,
    Job,
    JobKind,
    JobPosting,
    JobStatus,
    MatchScore,
    PostingStatus,
    RepoAnalysis,
    Repository,
    Role,
    User,
)
from firstdev.pipelines import match_jobs  # noqa: F401  (registers handlers)

CARD_KEYS = {
    "profile_id", "headline", "tier", "verified_skills", "cv_skills", "repos", "score",
    "reasons", "explained", "stale",
}  # fmt: skip
REPO_KEYS = {"name", "complexity", "summary"}


@pytest.fixture
def factory(engine):
    return sessionmaker(engine, expire_on_commit=False)


def review(adj=0, reason=""):
    return MatchReview(
        equivalences=[], adjustment=adj, adjustment_reason=reason, reasons=["fits well"],
        feedback=Feedback(strengths=["py"], missing_skills=["go"], suggestions=["learn go"]),
    )  # fmt: skip


def drain(factory, llm):
    n = 0
    while run_once(factory, HANDLERS, llm):
        n += 1
    return n


def verify(db, user_id, skills, repo_skills=(), gaps=()):
    """Parsed CV (with gaps) plus one analyzed repo whose languages prove `repo_skills`."""
    doc = CvDocument(profile_id=user_id, sha256="h", size=1, status=CvStatus.parsed)
    db.add(doc)
    db.flush()
    data = {"skills": [{"name": s, "years": None} for s in skills], "experience": [],
            "gaps": list(gaps)}  # fmt: skip
    db.add(CvParse(cv_document_id=doc.id, schema_version=1, model="m", data=data))
    repo = Repository(profile_id=user_id, owner="o", name="r")
    db.add(repo)
    db.flush()
    db.add(
        RepoAnalysis(
            repository_id=repo.id, commit_sha="a" * 40,
            metrics={"languages": {s.title(): 50_000 for s in repo_skills}},
            assessment={"complexity": "medium", "architecture_summary": "Clean layers.",
                        "best_practices": []},
            tutorial_likelihood=0.0, model="m",
        )
    )  # fmt: skip
    db.commit()


def make_dev(db, user_factory, email, skills=("python",), repo_skills=(), *, opted=True,
             verified=True, gaps=()):  # fmt: skip
    u = user_factory(email)
    p = db.get(DeveloperProfile, u.id)
    p.open_to_opportunities, p.headline = opted, f"Headline {email.split('@')[0]}"
    db.commit()
    if verified:
        verify(db, u.id, skills, repo_skills, gaps)
    return p


def make_posting(
    db, rec, title="Backend", required=("python", "fastapi"), status=PostingStatus.open
):
    p = JobPosting(recruiter_id=rec.id, title=title, description="SECRET-POSTING-TEXT",
                   required_skills=list(required), optional_skills=[], status=status)  # fmt: skip
    db.add(p)
    db.commit()
    return p


@pytest.fixture
def rec(register, login):
    r = register("rec@example.com", role="recruiter")
    return {"id": r["id"], "h": login("rec@example.com")}


@pytest.fixture
def pid(client, rec):
    body = {
        "title": "Backend",
        "description": "Build APIs",
        "required_skills": ["python", "fastapi"],
        "status": "open",
    }
    return client.post("/postings", json=body, headers=rec["h"]).json()["id"]


def rank(client, pid, h):
    return client.post(f"/postings/{pid}/rank", headers=h)


def candidates(client, pid, h):
    r = client.get(f"/postings/{pid}/candidates", headers=h)
    assert r.status_code == 200, r.text
    return r.json()


# --- rank + candidates -----------------------------------------------------------------------


def test_rank_filters_pool_and_orders_by_score(client, db, factory, user_factory, rec, pid):
    best = make_dev(db, user_factory, "best@x.com", ["python", "fastapi"], ["python", "fastapi"])
    mid = make_dev(db, user_factory, "mid@x.com", ["python", "fastapi"])
    low = make_dev(db, user_factory, "low@x.com", ["python"])
    out = make_dev(db, user_factory, "out@x.com", ["python", "fastapi"], opted=False)
    unv = make_dev(db, user_factory, "unv@x.com", verified=False)
    r = rank(client, pid, rec["h"])
    assert r.status_code == 202 and r.json()["job_id"]
    assert drain(factory, FakeLLM([review()] * 3)) >= 2
    cards = candidates(client, pid, rec["h"])
    assert [c["profile_id"] for c in cards] == [best.user_id, mid.user_id, low.user_id]
    assert [c["score"] for c in cards] == sorted((c["score"] for c in cards), reverse=True)
    assert out.user_id not in {c["profile_id"] for c in cards}
    assert unv.user_id not in {c["profile_id"] for c in cards}
    assert all(c["explained"] and not c["stale"] for c in cards)


def test_card_has_exact_allowlist(client, db, factory, user_factory, rec, pid):
    make_dev(db, user_factory, "a@x.com", ["python", "fastapi"], ["python"],
             gaps=[{"start": "2019-01", "end": "2019-06", "months": 6}])  # fmt: skip
    rank(client, pid, rec["h"])
    drain(factory, FakeLLM([review()]))
    (card,) = candidates(client, pid, rec["h"])
    assert set(card) == CARD_KEYS
    assert card["verified_skills"] == ["python"] and card["cv_skills"] == ["fastapi"]
    assert card["tier"] == "junior" and card["reasons"] == ["fits well"]
    assert len(card["repos"]) == 1 and set(card["repos"][0]) == REPO_KEYS
    assert card["repos"][0] == {"name": "o/r", "complexity": "medium", "summary": "Clean layers."}
    raw = str(card).lower()
    for banned in ("gap", "feedback", "adjustment", "learn go", "secret", "email", "@x.com"):
        assert banned not in raw


def test_rank_explains_only_top_20(client, db, factory, user_factory, rec, pid):
    for i in range(5):
        make_dev(db, user_factory, f"low{i}@x.com", ["java"])
    for i in range(20):
        make_dev(db, user_factory, f"hi{i}@x.com", ["python", "fastapi"], ["python"])
    rank(client, pid, rec["h"])
    llm = FakeLLM([review()] * 20)  # a 21st call would raise IndexError and fail the job
    drain(factory, llm)
    assert len(llm.calls) == 20
    assert {j.status for j in db.scalars(select(Job))} == {JobStatus.done}
    cards = candidates(client, pid, rec["h"])
    assert len(cards) == 25 and sum(c["explained"] for c in cards) == 20
    assert all(not c["explained"] for c in cards[20:]) and all(
        c["reasons"] == [] for c in cards[20:]
    )


def test_rank_caps_pool_at_50(client, db, factory, user_factory, rec, pid):
    for i in range(52):
        make_dev(db, user_factory, f"d{i}@x.com", ["python"])
    rank(client, pid, rec["h"])
    drain(factory, FakeLLM([review()] * 20))
    assert len(candidates(client, pid, rec["h"])) == 50


def test_profiles_without_vectors_are_appended(client, db, factory, user_factory, rec, pid):
    a = make_dev(db, user_factory, "a@x.com", ["python", "fastapi"])
    b = make_dev(db, user_factory, "b@x.com", ["python"])
    c = make_dev(db, user_factory, "c@x.com", ["fastapi"])
    enqueue_embed_profile(db, a.user_id)  # only a has a vector
    drain(factory, FakeLLM([]))
    rank(client, pid, rec["h"])
    drain(factory, FakeLLM([review()] * 3))
    ids = {x["profile_id"] for x in candidates(client, pid, rec["h"])}
    assert ids == {a.user_id, b.user_id, c.user_id}


def test_empty_pool_finishes(client, db, factory, user_factory, rec, pid):
    make_dev(db, user_factory, "out@x.com", opted=False)
    rank(client, pid, rec["h"])
    drain(factory, FakeLLM([]))
    assert {j.status for j in db.scalars(select(Job))} == {JobStatus.done}
    assert candidates(client, pid, rec["h"]) == []


def test_rank_twice_unchanged_makes_no_second_llm_call(client, db, factory, user_factory, rec, pid):
    make_dev(db, user_factory, "a@x.com", ["python"])
    rank(client, pid, rec["h"])
    drain(factory, FakeLLM([review()]))
    rank(client, pid, rec["h"])
    llm = FakeLLM([])
    drain(factory, llm)
    assert llm.calls == []
    assert {j.status for j in db.scalars(select(Job))} == {JobStatus.done}


def test_opt_out_after_ranking_hides_card(client, db, factory, user_factory, rec, pid):
    p = make_dev(db, user_factory, "a@x.com", ["python"])
    rank(client, pid, rec["h"])
    drain(factory, FakeLLM([review()]))
    assert len(candidates(client, pid, rec["h"])) == 1
    p.open_to_opportunities = False
    db.commit()
    assert candidates(client, pid, rec["h"]) == []


def test_stale_flag_after_posting_edit(client, db, factory, user_factory, rec, pid):
    make_dev(db, user_factory, "a@x.com", ["python"])
    rank(client, pid, rec["h"])
    drain(factory, FakeLLM([review()]))
    db.get(JobPosting, pid).required_skills = ["python", "go"]
    db.commit()
    (card,) = candidates(client, pid, rec["h"])
    assert card["stale"] is True


def test_other_recruiter_and_developer_get_404(client, db, register, login, rec, pid):
    register("rec2@example.com", role="recruiter")
    h2 = login("rec2@example.com")
    register("dev@example.com")
    hd = login("dev@example.com")
    for h in (h2, hd):
        assert rank(client, pid, h).status_code == 404
        assert client.get(f"/postings/{pid}/candidates", headers=h).status_code == 404
    assert rank(client, "missing", rec["h"]).status_code == 404
    assert db.scalars(select(Job).where(Job.kind == JobKind.rank_posting)).all() == []


def test_draft_and_closed_posting_404(client, db, user_factory, rec):
    owner = db.get(User, rec["id"])
    for status in (PostingStatus.draft, PostingStatus.closed):
        p = make_posting(db, owner, status=status)
        assert rank(client, p.id, rec["h"]).status_code == 404


def test_unauthenticated_rank_401(client, pid):
    assert client.post(f"/postings/{pid}/rank").status_code == 401


def test_sixth_rank_in_a_day_is_429(client, rec, pid, db):
    for _ in range(5):
        assert rank(client, pid, rec["h"]).status_code == 202
    assert rank(client, pid, rec["h"]).status_code == 429
    assert len(db.scalars(select(Job).where(Job.kind == JobKind.rank_posting)).all()) == 5


def test_rank_job_payload_is_ids_only(client, db, rec, pid):
    rank(client, pid, rec["h"])
    job = db.scalars(select(Job).where(Job.kind == JobKind.rank_posting)).one()
    assert job.payload == {"posting_id": pid} and job.user_id == rec["id"]


def test_rank_job_with_deleted_posting_is_noop(db, factory, user_factory):
    rec_user = user_factory("r@x.com", Role.recruiter)
    enqueue(db, rec_user, JobKind.rank_posting, {"posting_id": "gone"})
    enqueue(db, rec_user, JobKind.rank_posting, {})
    assert drain(factory, FakeLLM([])) == 2
    assert {j.status for j in db.scalars(select(Job))} == {JobStatus.done}


# --- recommended jobs ------------------------------------------------------------------------


@pytest.fixture
def dev(client, register, login, db):
    me = register("dev@example.com")
    verify(db, me["id"], ["python", "fastapi"], ["python"])
    return {"id": me["id"], "h": login("dev@example.com")}


def embed_all(db, factory, dev_id, *postings):
    rec_user = db.get(User, postings[0].recruiter_id)
    for p in postings:
        enqueue(db, rec_user, JobKind.embed_posting, {"posting_id": p.id})
    enqueue_embed_profile(db, dev_id)
    drain(factory, FakeLLM([]))


def test_recommended_orders_by_base_score(client, db, factory, dev, user_factory):
    rec_user = user_factory("r@x.com", Role.recruiter)
    good = make_posting(db, rec_user, "Good", ["python", "fastapi"])
    bad = make_posting(db, rec_user, "Bad", ["cobol", "fortran"])
    closed = make_posting(db, rec_user, "Closed", ["python"], PostingStatus.closed)
    draft = make_posting(db, rec_user, "Draft", ["python"], PostingStatus.draft)
    embed_all(db, factory, dev["id"], good, bad, closed, draft)
    r = client.get("/me/recommended-jobs", headers=dev["h"])
    assert r.status_code == 200
    jobs = r.json()["jobs"]
    assert [j["posting_id"] for j in jobs] == [good.id, bad.id]
    assert set(jobs[0]) == {"posting_id", "title", "tier", "location", "remote", "score",
                            "matched", "missing"}  # fmt: skip
    assert jobs[0]["matched"] == ["python", "fastapi"] and jobs[0]["missing"] == []
    assert jobs[1]["missing"] == ["cobol", "fortran"] and jobs[0]["score"] > jobs[1]["score"]


def test_recommended_caps_at_20(client, db, factory, dev, user_factory):
    rec_user = user_factory("r@x.com", Role.recruiter)
    ps = [make_posting(db, rec_user, f"P{i}", ["python"]) for i in range(25)]
    embed_all(db, factory, dev["id"], *ps)
    assert len(client.get("/me/recommended-jobs", headers=dev["h"]).json()["jobs"]) == 20


def test_recommended_no_vector_returns_reason(client, dev, db, user_factory):
    make_posting(db, user_factory("r@x.com", Role.recruiter))
    r = client.get("/me/recommended-jobs", headers=dev["h"])
    assert r.status_code == 200
    assert r.json() == {"jobs": [], "reason": "profile not verified yet"}


def test_recommended_uses_no_llm_and_writes_nothing(client, db, factory, dev, user_factory):
    rec_user = user_factory("r@x.com", Role.recruiter)
    p = make_posting(db, rec_user)
    embed_all(db, factory, dev["id"], p)
    llm = FakeLLM([])
    client.app.dependency_overrides[get_llm] = lambda: llm
    rows = lambda m: db.scalar(select(func.count()).select_from(m))  # noqa: E731
    scores, jobs = rows(MatchScore), rows(Job)
    assert len(client.get("/me/recommended-jobs", headers=dev["h"]).json()["jobs"]) == 1
    assert llm.calls == [] and rows(MatchScore) == scores == 0 and rows(Job) == jobs


def test_recommended_requires_developer(client, rec):
    assert client.get("/me/recommended-jobs", headers=rec["h"]).status_code == 404
    assert client.get("/me/recommended-jobs").status_code == 401


# --- developer feedback ----------------------------------------------------------------------

GAP = {"start": "2019-01", "end": "2019-06", "months": 6}


@pytest.fixture
def gap_dev(client, register, login, db):
    me = register("gap@example.com")
    verify(db, me["id"], ["python"], ["python"], gaps=[GAP])
    return {"id": me["id"], "h": login("gap@example.com")}


def test_match_feedback_202_then_200(client, db, factory, gap_dev, pid):
    r = client.get(f"/me/matches/{pid}", headers=gap_dev["h"])
    assert r.status_code == 202
    job = db.get(Job, r.json()["job_id"])
    assert (job.kind, job.user_id) == (JobKind.score_pair, gap_dev["id"])
    assert job.payload == {
        "posting_id": pid,
        "profile_id": gap_dev["id"],
        "explain": True,
        "on_demand": True,
    }
    drain(factory, FakeLLM([review(3, "evidence")]))
    r = client.get(f"/me/matches/{pid}", headers=gap_dev["h"])
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"score", "components", "feedback", "explained", "gaps"}
    assert body["explained"] is True and 0 <= body["score"] <= 100
    assert "reasons" not in body and "reasons" not in str(body["feedback"])
    assert body["feedback"]["suggestions"] == ["learn go"]
    assert "adjustment_reason" not in body["components"] and "equivalences" in body["components"]
    assert body["gaps"] == ["6 months without a listed job between 2019-01 and 2019-06"]


def test_gaps_only_on_developer_route(client, db, factory, gap_dev, pid, rec):
    client.post(f"/postings/{pid}/apply", headers=gap_dev["h"])
    client.get(f"/me/matches/{pid}", headers=gap_dev["h"])
    drain(factory, FakeLLM([review(), review()]))
    rank(client, pid, rec["h"])
    db.get(DeveloperProfile, gap_dev["id"]).open_to_opportunities = True
    db.commit()
    drain(factory, FakeLLM([review()]))
    texts = [
        client.get(f"/postings/{pid}/candidates", headers=rec["h"]).text,
        client.get(f"/postings/{pid}/applications", headers=rec["h"]).text,
    ]
    assert "fits well" in texts[0] and "score" in texts[1]
    for t in texts:
        assert "gap" not in t.lower() and "2019" not in t


def test_match_without_gaps_has_empty_list(client, db, factory, dev, pid):
    client.get(f"/me/matches/{pid}", headers=dev["h"])
    drain(factory, FakeLLM([review()]))
    assert client.get(f"/me/matches/{pid}", headers=dev["h"]).json()["gaps"] == []


def test_each_developer_gets_only_their_own_match(client, db, factory, register, login, dev, pid):
    me2 = register("other@example.com")
    verify(db, me2["id"], ["java"])
    h2 = login("other@example.com")
    for h in (dev["h"], h2):
        client.get(f"/me/matches/{pid}", headers=h)
    drain(factory, FakeLLM([review(), review()]))
    s1 = client.get(f"/me/matches/{pid}", headers=dev["h"]).json()["score"]
    s2 = client.get(f"/me/matches/{pid}", headers=h2).json()["score"]
    by_profile = {m.profile_id: m.score for m in db.scalars(select(MatchScore))}
    assert by_profile == {dev["id"]: s1, me2["id"]: s2} and s1 > s2


def test_stale_match_requeues(client, db, factory, dev, pid):
    client.get(f"/me/matches/{pid}", headers=dev["h"])
    drain(factory, FakeLLM([review()]))
    assert client.get(f"/me/matches/{pid}", headers=dev["h"]).status_code == 200
    db.get(JobPosting, pid).required_skills = ["python", "go"]
    db.commit()
    assert client.get(f"/me/matches/{pid}", headers=dev["h"]).status_code == 202


def test_unexplained_score_requeues(client, db, factory, dev, pid):
    me = db.get(User, dev["id"])
    enqueue(db, me, JobKind.score_pair,
            {"posting_id": pid, "profile_id": dev["id"], "explain": False})  # fmt: skip
    drain(factory, FakeLLM([]))
    assert client.get(f"/me/matches/{pid}", headers=dev["h"]).status_code == 202


def _finish(db, job_id):
    db.get(Job, job_id).status = JobStatus.done  # finished without an explained score
    db.commit()


def test_match_21st_request_is_429(client, dev, pid, db):
    for _ in range(20):
        r = client.get(f"/me/matches/{pid}", headers=dev["h"])
        assert r.status_code == 202
        _finish(db, r.json()["job_id"])
    assert client.get(f"/me/matches/{pid}", headers=dev["h"]).status_code == 429
    assert len(db.scalars(select(Job).where(Job.kind == JobKind.score_pair)).all()) == 20


def test_polling_reuses_in_flight_job(client, dev, pid, db):
    first = client.get(f"/me/matches/{pid}", headers=dev["h"]).json()["job_id"]
    for _ in range(5):
        r = client.get(f"/me/matches/{pid}", headers=dev["h"])
        assert r.status_code == 202 and r.json()["job_id"] == first
    assert len(db.scalars(select(Job).where(Job.kind == JobKind.score_pair)).all()) == 1


def test_apply_jobs_do_not_use_on_demand_quota(client, dev, pid, db):
    from firstdev.jobs import enqueue

    user = db.get(User, dev["id"])
    for _ in range(25):  # score jobs created by applying carry no on_demand flag
        j = enqueue(
            db,
            user,
            JobKind.score_pair,
            {"posting_id": "other", "profile_id": dev["id"], "explain": True},
        )
        _finish(db, j.id)
    assert client.get(f"/me/matches/{pid}", headers=dev["h"]).status_code == 202


def test_match_non_open_missing_or_recruiter_404(client, db, dev, rec, user_factory):
    owner = db.get(User, rec["id"])
    draft = make_posting(db, owner, status=PostingStatus.draft)
    closed = make_posting(db, owner, status=PostingStatus.closed)
    for pid_ in (draft.id, closed.id, "missing"):
        assert client.get(f"/me/matches/{pid_}", headers=dev["h"]).status_code == 404
    assert client.get(f"/me/matches/{draft.id}", headers=rec["h"]).status_code == 404
    assert client.get("/me/matches/x").status_code == 401
    assert db.scalars(select(Job).where(Job.kind == JobKind.score_pair)).all() == []
