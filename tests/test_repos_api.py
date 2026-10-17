# Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform.
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker
from test_repo_analyzer import FakeGitHub, assess

from firstdev.github import RepoNotFound
from firstdev.jobs import HANDLERS, run_once
from firstdev.llm import FakeLLM
from firstdev.models import Job, RepoAnalysis, Repository
from firstdev.pipelines import repo_analyzer

URL = "/profiles/me/repos"


@pytest.fixture
def factory(engine):
    return sessionmaker(engine, expire_on_commit=False)


@pytest.fixture
def add(client, dev_headers):
    def _add(url="https://github.com/octo/hello", headers=None, **body):
        return client.post(URL, json={"url": url, **body}, headers=headers or dev_headers)

    return _add


@pytest.fixture
def work(factory, monkeypatch):
    def _work(gh, *responses):
        monkeypatch.setattr(repo_analyzer, "get_github", lambda: gh)
        assert run_once(factory, HANDLERS, FakeLLM(list(responses)))

    return _work


def count(factory, model):
    with factory() as s:
        return s.scalar(select(func.count()).select_from(model))


def test_flow_202_run_get(client, dev_headers, add, work, factory):
    r = add()
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["status"] == "queued"
    got = client.get(f"/repos/{body['repo_id']}/analysis", headers=dev_headers).json()
    assert got["status"] == "queued" and got["analysis"] is None
    assert (got["repo"]["owner"], got["repo"]["name"]) == ("octo", "hello")
    work(FakeGitHub({"README.md": "# hi", "a.py": "x = 1"}), assess(complexity=2))
    got = client.get(f"/repos/{body['repo_id']}/analysis", headers=dev_headers).json()
    assert got["status"] == "done" and got["last_error"] is None
    assert got["repo"]["stars"] == 7
    a = got["analysis"]
    assert a["model"] == "fake-model" and a["assessment"]["complexity"] == 2
    assert a["metrics"]["fetched_files"] == 2 and len(a["commit_sha"]) == 40
    with factory() as s:
        assert s.get(Job, body["job_id"]).payload == {"repository_id": body["repo_id"]}


def test_failed_job_visible_with_safe_error(client, dev_headers, add, work):
    rid = add().json()["repo_id"]
    work(FakeGitHub({}, error=RepoNotFound("repository not found or private")))
    got = client.get(f"/repos/{rid}/analysis", headers=dev_headers).json()
    assert got["status"] == "failed" and got["analysis"] is None
    assert got["last_error"] == "RepoNotFound: repository not found or private"


def test_duplicate_while_queued_returns_same_job(add, factory):
    first = add().json()
    r = add("https://github.com/OCTO/hello.git")  # case/.git variants are the same repo
    assert r.status_code == 200
    assert r.json()["job_id"] == first["job_id"] and r.json()["repo_id"] == first["repo_id"]
    assert count(factory, Job) == 1 and count(factory, Repository) == 1


def test_reanalyze_after_done_enqueues_again(add, work, factory):
    first = add().json()
    work(FakeGitHub({"a.py": "x"}), assess())
    r = add()
    assert r.status_code == 202 and r.json()["job_id"] != first["job_id"]
    assert r.json()["repo_id"] == first["repo_id"]


def test_quota_21st_429(add, factory):
    for i in range(20):
        assert add(f"https://github.com/octo/r{i}").status_code == 202
    assert add("https://github.com/octo/r20").status_code == 429
    assert count(factory, Job) == 20


def test_51st_repo_409(add, factory):
    for i in range(50):
        assert add(f"https://github.com/octo/r{i}").status_code == 202
        with factory() as s:  # backdate jobs so the daily quota doesn't hide the repo limit
            s.query(Job).update({Job.created_at: datetime(2020, 1, 1, tzinfo=UTC)})
            s.commit()
    assert add("https://github.com/octo/r50").status_code == 409
    assert add("https://github.com/octo/r0").status_code == 200  # existing repo, job still queued


def test_recruiter_404_and_unauth_401(client, register, login, add):
    register("rec@example.com", role="recruiter")
    assert add(headers=login("rec@example.com")).status_code == 404
    assert client.post(URL, json={"url": "https://github.com/o/r"}).status_code == 401
    assert client.get("/repos/x/analysis").status_code == 401


def test_other_users_analysis_404(client, add, register, login, dev_headers):
    rid = add().json()["repo_id"]
    register("other@example.com")
    assert (
        client.get(f"/repos/{rid}/analysis", headers=login("other@example.com")).status_code == 404
    )
    assert client.get(f"/repos/{rid}/analysis", headers=dev_headers).status_code == 200
    assert client.get("/repos/nope/analysis", headers=dev_headers).status_code == 404


@pytest.mark.parametrize(
    "url",
    [
        "http://github.com/o/r",
        "https://github.com.evil.com/o/r",
        "https://github.com/o/r/tree/main",
        "https://github.com/o/..",
        "file:///etc/passwd",
        "",
        "   ",
        "https://github.com/" + "a" * 300,
    ],
)
def test_invalid_urls_422(add, factory, url):
    assert add(url).status_code == 422
    assert count(factory, Repository) == 0 and count(factory, Job) == 0


def test_extra_fields_and_missing_url_422(client, dev_headers, add):
    assert add(extra="x").status_code == 422
    assert client.post(URL, json={}, headers=dev_headers).status_code == 422


def test_delete_me_cascades_repos_and_analyses(client, dev_headers, add, work, factory):
    add()
    work(FakeGitHub({"a.py": "x = 1"}), assess())
    assert count(factory, RepoAnalysis) == 1
    r = client.request(
        "DELETE", "/me", headers=dev_headers, json={"password": "correct horse battery"}
    )
    assert r.status_code == 204, r.text
    assert count(factory, Repository) == 0 and count(factory, RepoAnalysis) == 0


def test_overview_empty_then_with_repo(client, dev_headers, add):
    r = client.get("/profiles/me/overview", headers=dev_headers)
    assert r.status_code == 200
    assert r.json() == {"verified": False, "cv": None, "repos": [], "skills": []}
    add()
    got = client.get("/profiles/me/overview", headers=dev_headers).json()
    assert [(x["owner"], x["name"], x["status"]) for x in got["repos"]] == [
        ("octo", "hello", "queued")
    ]
    assert got["verified"] is False


def test_overview_is_developer_only(client, register, login):
    register("rec@example.com", role="recruiter")
    rec_headers = login("rec@example.com")
    assert client.get("/profiles/me/overview", headers=rec_headers).status_code == 404
