# Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform.
"""Minimal read-only GitHub REST client. Fixed base URL, so user input can never steer a request
to another host (SSRF); repo contents are only ever read as text, never cloned or executed."""

import base64
import binascii
import re
import time
from typing import Any
from urllib.parse import quote

import httpx

from firstdev.config import get_settings
from firstdev.errors import TransientError

BASE_URL = "https://api.github.com"
MAX_JSON_BYTES = 5 * 1024 * 1024
MAX_BLOB_BYTES = 100 * 1024

_URL_RE = re.compile(
    r"https://github\.com/([A-Za-z0-9](?:[A-Za-z0-9]|-(?=[A-Za-z0-9])){0,38})"
    r"/([A-Za-z0-9._-]{1,100}?)(?:\.git)?/?"
)


class GitHubError(Exception):
    """Messages are fixed strings (safe to show users); never put response text in them."""


class InvalidRepoUrl(GitHubError, ValueError):
    pass


class RepoNotFound(GitHubError):
    pass


class RepoMoved(GitHubError):
    pass


class GitHubTransientError(GitHubError, TransientError):
    pass


def parse_repo_url(url: str) -> tuple[str, str]:
    m = _URL_RE.fullmatch(url.strip())
    # Dot names would resolve as path traversal-ish segments ("." / "..") or hidden files.
    if m is None or m[2].startswith("."):
        raise InvalidRepoUrl("not a valid GitHub repository URL")
    return m[1], m[2]


def _seg(s: str) -> str:
    return quote(s, safe="")


class GitHubClient:
    def __init__(self, token: str | None = None):
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "FirstDev",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self._http = httpx.Client(
            base_url=BASE_URL, timeout=10, follow_redirects=False, headers=headers
        )

    def close(self) -> None:
        self._http.close()

    def _get(self, path: str, **params: Any) -> Any:
        try:
            resp = self._http.get(path, params=params or None)
        except httpx.HTTPError:
            raise GitHubTransientError("GitHub unreachable or timed out") from None
        code = resp.status_code
        if code in (404, 451):
            raise RepoNotFound("repository not found or private")
        if code in (301, 302, 307, 308):
            raise RepoMoved("repository moved; submit its new URL")
        if code in (403, 429):
            h = resp.headers
            if h.get("x-ratelimit-remaining") == "0" or "retry-after" in h:
                raise GitHubTransientError(f"rate limited; resets in {_reset_seconds(h)}s")
            raise GitHubError("access denied")
        if code >= 500:
            raise GitHubTransientError("GitHub server error")
        if code == 409:
            return None  # git data API answers 409 for an empty repository
        if code != 200:
            raise GitHubError("unexpected GitHub response")
        if len(resp.content) > MAX_JSON_BYTES:
            raise GitHubError("response too large")
        try:
            return resp.json()
        except ValueError:
            raise GitHubError("invalid GitHub response") from None

    def repo(self, owner: str, name: str) -> dict:
        data = self._get(f"/repos/{_seg(owner)}/{_seg(name)}")
        if not isinstance(data, dict) or data.get("private"):
            raise RepoNotFound("repository not found or private")  # private is out of scope
        return data

    def languages(self, owner: str, name: str) -> dict[str, int]:
        data = self._get(f"/repos/{_seg(owner)}/{_seg(name)}/languages")
        return data if isinstance(data, dict) else {}

    def commits(self, owner: str, name: str, limit: int = 100) -> list[dict]:
        data = self._get(
            f"/repos/{_seg(owner)}/{_seg(name)}/commits", per_page=100
        )  # one page only
        return data[:limit] if isinstance(data, list) else []

    def tree(self, owner: str, name: str, sha: str) -> tuple[list[dict], bool]:
        data = self._get(f"/repos/{_seg(owner)}/{_seg(name)}/git/trees/{_seg(sha)}", recursive=1)
        if not isinstance(data, dict):
            return [], False
        return list(data.get("tree") or []), bool(data.get("truncated"))

    def blob(self, owner: str, name: str, sha: str) -> bytes:
        data = self._get(f"/repos/{_seg(owner)}/{_seg(name)}/git/blobs/{_seg(sha)}")
        if not isinstance(data, dict) or data.get("encoding") != "base64":
            raise GitHubError("unexpected blob encoding")
        if not isinstance(data.get("size"), int) or data["size"] > MAX_BLOB_BYTES:
            raise GitHubError("blob too large")
        try:
            return base64.b64decode(data.get("content", ""))
        except (binascii.Error, ValueError):
            raise GitHubError("invalid blob content") from None


def _reset_seconds(headers: httpx.Headers) -> int:
    try:
        if "retry-after" in headers:
            return max(0, int(headers["retry-after"]))
        return max(0, int(headers["x-ratelimit-reset"]) - int(time.time()))
    except (KeyError, ValueError):
        return 0


def get_github() -> GitHubClient:
    """Provider so tests can replace it, like get_llm."""
    t = get_settings().github_token
    return GitHubClient(t.get_secret_value() if t else None)
