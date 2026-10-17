# Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform.
import base64

import httpx
import pytest
import respx

from firstdev.config import Settings
from firstdev.errors import TransientError
from firstdev.github import (
    GitHubClient,
    GitHubError,
    GitHubTransientError,
    InvalidRepoUrl,
    RepoMoved,
    RepoNotFound,
    parse_repo_url,
)

API = "https://api.github.com"


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://github.com/octocat/hello", ("octocat", "hello")),
        ("https://github.com/octocat/hello/", ("octocat", "hello")),
        ("https://github.com/octocat/hello.git", ("octocat", "hello")),
        ("  https://github.com/octocat/hello \n", ("octocat", "hello")),
        ("https://github.com/o-c/my.repo_name-1", ("o-c", "my.repo_name-1")),
        ("https://github.com/a/b", ("a", "b")),
    ],
)
def test_parse_ok(url, expected):
    assert parse_repo_url(url) == expected


@pytest.mark.parametrize(
    "url",
    [
        "http://github.com/o/r",
        "https://github.com.evil.com/o/r",
        "https://evil.com/github.com/o/r",
        "https://user@github.com/o/r",
        "https://user:pw@github.com/o/r",
        "https://github.com:443/o/r",
        "https://github.com/o/r?x=1",
        "https://github.com/o/r#frag",
        "https://github.com/o/r/tree/main",
        "https://github.com/o/..",
        "https://github.com/o/.",
        "https://github.com/o/.hidden",
        "https://github.com/o--x/r",
        "https://github.com/-o/r",
        "https://github.com/o-/r",
        "https://github.com/" + "a" * 40 + "/r",
        "https://github.com/o/" + "r" * 101,
        "file:///etc/passwd",
        "javascript:alert(1)",
        "",
        "   ",
        "https://gıthub.com/o/r",  # dotless i lookalike
        "https://github.com/o/r\nx",
        "https://github.com/o/r%2f..",
        "https://github.com//r",
    ],
)
def test_parse_rejects(url):
    with pytest.raises(InvalidRepoUrl):
        parse_repo_url(url)


def test_boundary_owner_39_ok():
    assert parse_repo_url("https://github.com/" + "a" * 39 + "/r")[0] == "a" * 39


def client(token=None):
    return GitHubClient(token)


@respx.mock
def test_404_and_451_not_found():
    respx.get(f"{API}/repos/o/r").respond(404)
    with pytest.raises(RepoNotFound, match="not found or private"):
        client().repo("o", "r")
    respx.get(f"{API}/repos/o/r").respond(451)
    with pytest.raises(RepoNotFound):
        client().repo("o", "r")


@respx.mock
def test_private_is_not_found():
    respx.get(f"{API}/repos/o/r").respond(200, json={"private": True, "name": "r"})
    with pytest.raises(RepoNotFound):
        client().repo("o", "r")


@respx.mock
def test_public_metadata_returned():
    respx.get(f"{API}/repos/o/r").respond(200, json={"private": False, "name": "r"})
    assert client().repo("o", "r")["name"] == "r"


@respx.mock
@pytest.mark.parametrize("code", [301, 302, 307])
def test_redirect_not_followed(code):
    target = respx.get("https://evil.example/x").respond(200, json={})
    respx.get(f"{API}/repos/o/r").respond(code, headers={"location": "https://evil.example/x"})
    with pytest.raises(RepoMoved, match="submit its new URL"):
        client().repo("o", "r")
    assert not target.called


@respx.mock
@pytest.mark.parametrize(
    "headers",
    [{"x-ratelimit-remaining": "0", "x-ratelimit-reset": "9999999999"}, {"retry-after": "30"}],
)
@pytest.mark.parametrize("code", [403, 429])
def test_rate_limit_transient(code, headers):
    respx.get(f"{API}/repos/o/r").respond(code, headers=headers)
    with pytest.raises(GitHubTransientError, match=r"resets in \d+s") as ei:
        client().repo("o", "r")
    assert isinstance(ei.value, TransientError)


@respx.mock
def test_plain_403_is_access_denied():
    respx.get(f"{API}/repos/o/r").respond(403, text="secret details")
    with pytest.raises(GitHubError, match="access denied") as ei:
        client().repo("o", "r")
    assert not isinstance(ei.value, GitHubTransientError)


@respx.mock
def test_5xx_transient():
    respx.get(f"{API}/repos/o/r").respond(503)
    with pytest.raises(GitHubTransientError):
        client().repo("o", "r")


@respx.mock
@pytest.mark.parametrize("exc", [httpx.ReadTimeout("t"), httpx.ConnectError("c")])
def test_timeout_and_connection_errors_transient(exc):
    respx.get(f"{API}/repos/o/r").mock(side_effect=exc)
    with pytest.raises(GitHubTransientError):
        client().repo("o", "r")


@respx.mock
def test_empty_repo_commits_409():
    respx.get(f"{API}/repos/o/r/commits").respond(409, json={"message": "Git Repository is empty."})
    assert client().commits("o", "r") == []


@respx.mock
def test_commits_one_page_and_limit():
    route = respx.get(f"{API}/repos/o/r/commits").respond(200, json=[{"sha": "a"}] * 100)
    assert len(client().commits("o", "r", limit=100)) == 100
    assert len(client().commits("o", "r", limit=5)) == 5
    assert route.calls[0].request.url.params["per_page"] == "100"


@respx.mock
def test_oversized_response_rejected():
    respx.get(f"{API}/repos/o/r/languages").respond(200, content=b"{" + b" " * (5 * 1024 * 1024))
    with pytest.raises(GitHubError, match="response too large"):
        client().languages("o", "r")


@respx.mock
def test_blob_decoded_and_size_limit():
    body = base64.b64encode(b"hello").decode()
    respx.get(f"{API}/repos/o/r/git/blobs/abc").respond(
        200, json={"content": body, "encoding": "base64", "size": 5}
    )
    assert client().blob("o", "r", "abc") == b"hello"
    respx.get(f"{API}/repos/o/r/git/blobs/big").respond(
        200, json={"content": "", "encoding": "base64", "size": 100 * 1024 + 1}
    )
    with pytest.raises(GitHubError, match="blob too large"):
        client().blob("o", "r", "big")


@respx.mock
def test_tree_returns_entries_and_truncated():
    route = respx.get(f"{API}/repos/o/r/git/trees/abc").respond(
        200, json={"tree": [{"path": "a", "type": "blob"}], "truncated": True}
    )
    entries, truncated = client().tree("o", "r", "abc")
    assert entries[0]["path"] == "a" and truncated is True
    assert route.calls[0].request.url.params["recursive"] == "1"


@respx.mock
def test_auth_header_only_with_token():
    route = respx.get(f"{API}/repos/o/r/languages").respond(200, json={})
    client().languages("o", "r")
    client("tok123").languages("o", "r")
    plain, authed = (c.request.headers for c in route.calls)
    assert "authorization" not in plain
    assert authed["authorization"] == "Bearer tok123"
    assert authed["accept"] == "application/vnd.github+json"
    assert authed["x-github-api-version"] == "2022-11-28" and authed["user-agent"] == "FirstDev"


@respx.mock
def test_path_segments_escaped():
    route = respx.get(url__regex=r"https://api\.github\.com/.*").respond(200, json={})
    client().languages("o/../x", "r?y#z")
    assert str(route.calls[0].request.url) == f"{API}/repos/o%2F..%2Fx/r%3Fy%23z/languages"


def test_token_from_unprefixed_env(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_fake")
    s = Settings(_env_file=None)
    assert s.github_token.get_secret_value() == "ghp_fake"
    assert "ghp_fake" not in repr(s)
    monkeypatch.delenv("GITHUB_TOKEN")
    assert Settings(_env_file=None).github_token is None
