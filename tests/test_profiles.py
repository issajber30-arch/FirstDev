# Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform.
import pytest

URL = "/profiles/me"


def test_new_developer_has_empty_profile(client, dev_headers):
    r = client.get(URL, headers=dev_headers)
    assert r.status_code == 200
    body = r.json()
    assert body.pop("open_to_opportunities") is False  # discovery is opt-in
    assert body.pop("public_profile") is False  # so is the public page
    assert set(body.values()) == {None}


def test_put_get_roundtrip(client, dev_headers):
    body = {
        "headline": "  Backend dev  ",
        "bio": "I build things",
        "location": "Haifa",
        "experience_tier": "junior",
        "github_username": "octo-cat",
    }
    r = client.put(URL, json=body, headers=dev_headers)
    assert r.status_code == 200
    assert r.json() == {
        **body,
        "headline": "Backend dev",
        "open_to_opportunities": False,
        "handle": None,
        "public_profile": False,
    }
    assert client.get(URL, headers=dev_headers).json() == r.json()


def test_put_replaces_and_clears(client, dev_headers):
    client.put(URL, json={"headline": "x", "bio": "y"}, headers=dev_headers)
    r = client.put(URL, json={"bio": "z"}, headers=dev_headers)
    assert r.json()["headline"] is None and r.json()["bio"] == "z"


def test_hebrew_and_emoji_accepted(client, dev_headers):
    body = {"headline": "מפתח צעיר 👩‍💻", "bio": "שלום עולם 🚀", "location": "תל אביב"}
    r = client.put(URL, json=body, headers=dev_headers)
    assert r.status_code == 200 and r.json()["headline"] == body["headline"]


@pytest.mark.parametrize(("field", "limit"), [("headline", 120), ("bio", 2000), ("location", 100)])
def test_length_boundaries(client, dev_headers, field, limit):
    assert client.put(URL, json={field: "a" * limit}, headers=dev_headers).status_code == 200
    assert client.put(URL, json={field: "a" * (limit + 1)}, headers=dev_headers).status_code == 422


@pytest.mark.parametrize("field", ["headline", "bio", "location", "github_username"])
@pytest.mark.parametrize("value", ["", "   "])
def test_empty_strings_rejected(client, dev_headers, field, value):
    assert client.put(URL, json={field: value}, headers=dev_headers).status_code == 422


@pytest.mark.parametrize(
    "name", ["-abc", "abc-", "a--b", "a" * 40, "a b", "a_b", "אבג", "a/b", "a.b"]
)
def test_bad_github_usernames(client, dev_headers, name):
    assert client.put(URL, json={"github_username": name}, headers=dev_headers).status_code == 422


@pytest.mark.parametrize("name", ["a", "a-b", "A1-b2-c3", "a" * 39])
def test_good_github_usernames(client, dev_headers, name):
    assert client.put(URL, json={"github_username": name}, headers=dev_headers).status_code == 200


def test_bad_tier_and_extra_fields(client, dev_headers):
    assert (
        client.put(URL, json={"experience_tier": "senior"}, headers=dev_headers).status_code == 422
    )
    assert client.put(URL, json={"user_id": "x"}, headers=dev_headers).status_code == 422


def test_profile_requires_auth(client):
    assert client.get(URL).status_code == 401
    assert client.put(URL, json={}).status_code == 401


def test_recruiter_gets_404(client, register, login):
    register("rec@example.com", role="recruiter")
    h = login("rec@example.com")
    assert client.get(URL, headers=h).status_code == 404
    assert client.put(URL, json={"headline": "x"}, headers=h).status_code == 404
