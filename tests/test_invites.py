# Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform.
import hashlib
import os
import re
import subprocess
import sys

import pytest
from conftest import PASSWORD, ROOT
from sqlalchemy import select

from firstdev import invites
from firstdev.models import InviteCode, User

CODE_RE = re.compile(r"^[A-HJ-NP-Z2-9]{4}-[A-HJ-NP-Z2-9]{4}-[A-HJ-NP-Z2-9]{4}$")


@pytest.fixture
def cli(engine):
    def run(*args, check=True):
        env = {
            **os.environ,
            "FIRSTDEV_DATABASE_URL": str(engine.url),
            "FIRSTDEV_ENV": "dev",
        }
        p = subprocess.run(  # noqa: S603 - fixed argv, test-controlled
            [sys.executable, str(ROOT / "scripts" / "invites.py"), *args],
            env=env,
            capture_output=True,
            text=True,
            cwd=ROOT,
        )
        if check:
            assert p.returncode == 0, p.stderr
        return p

    return run


@pytest.fixture
def invite_required(set_env):
    set_env(require_invite="true")


def _body(code=None, **kw):
    b = {
        "email": "n@example.com",
        "password": PASSWORD,
        "role": "developer",
        "display_name": "Noa",
        **kw,
    }
    if code is not None:
        b["invite_code"] = code
    return b


def test_code_format_and_alphabet():
    codes = {invites.generate_code() for _ in range(200)}
    assert len(codes) == 200 and all(CODE_RE.match(c) for c in codes)
    assert len(invites.ALPHABET) == 32 and not set("IO01") & set(invites.ALPHABET)


def test_cli_create_list_revoke(cli, db):
    out = cli("create", "--label", "Dana (Wix)").stdout
    code = re.search(r"[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4}", out).group()
    assert CODE_RE.match(code)
    row = db.scalars(select(InviteCode)).one()
    assert row.code_hash == hashlib.sha256(code.replace("-", "").encode()).hexdigest()
    assert row.label == "Dana (Wix)"

    listing = cli("list").stdout
    assert "Dana (Wix)" in listing and row.id in listing and "unused" in listing
    assert code not in listing and code.replace("-", "") not in listing
    assert row.code_hash not in listing

    cli("revoke", "--id", row.id)
    assert "revoked" in cli("list").stdout
    assert cli("revoke", "--id", "does-not-exist", check=False).returncode == 1


def test_cli_revoke_by_label(cli, db):
    cli("create", "--label", "x")
    cli("revoke", "--label", "x")
    db.expire_all()
    assert db.scalars(select(InviteCode)).one().revoked_at is not None
    assert cli("revoke", "--label", "x", check=False).returncode == 1  # nothing left to revoke


def test_cli_label_validation(cli):
    assert cli("create", "--label", "", check=False).returncode != 0
    assert cli("create", "--label", "x" * 101, check=False).returncode != 0


def test_register_with_valid_code_then_reuse(client, cli, db, invite_required):
    code = re.search(r"\S+-\S+-\S+", cli("create", "--label", "a").stdout).group()
    r = client.post("/auth/register", json=_body(code))
    assert r.status_code == 201 and r.json()["display_name"] == "Noa"
    row = db.scalars(select(InviteCode)).one()
    assert row.used_at is not None and row.used_by == r.json()["id"]
    r2 = client.post("/auth/register", json=_body(code, email="m@example.com"))
    assert r2.status_code == 403


def test_bad_codes_all_look_the_same(client, cli, db, invite_required):
    used = re.search(r"\S+-\S+-\S+", cli("create", "--label", "u").stdout).group()
    revoked = re.search(r"\S+-\S+-\S+", cli("create", "--label", "r").stdout).group()
    cli("revoke", "--label", "r")
    assert client.post("/auth/register", json=_body(used)).status_code == 201
    bodies = [
        client.post("/auth/register", json=_body(c, email=f"z{i}@example.com"))
        for i, c in enumerate([used, revoked, "AAAA-BBBB-CCCC", "", None])
    ]
    assert {r.status_code for r in bodies} == {403}
    assert len({r.text for r in bodies}) == 1
    assert bodies[0].json() == {"detail": "invalid invite code"}


def test_code_input_normalised(client, cli, invite_required):
    code = re.search(r"\S+-\S+-\S+", cli("create", "--label", "a").stdout).group()
    messy = " " + code.replace("-", "").lower() + " "
    assert client.post("/auth/register", json=_body(messy)).status_code == 201


def test_sixth_bad_code_is_429(client, invite_required):
    codes = [
        client.post("/auth/register", json=_body("AAAA-BBBB-CCCC")).status_code for _ in range(6)
    ]
    assert codes == [403] * 5 + [429]


def test_duplicate_email_does_not_burn_code(client, cli, db, invite_required):
    db.add(User(email="n@example.com", password_hash="h", role="developer"))
    db.commit()
    code = re.search(r"\S+-\S+-\S+", cli("create", "--label", "a").stdout).group()
    assert client.post("/auth/register", json=_body(code)).status_code == 409
    db.expire_all()
    assert db.scalars(select(InviteCode)).one().used_at is None


def test_invite_not_checked_when_disabled(client):
    assert client.post("/auth/register", json=_body()).status_code == 201


@pytest.mark.parametrize(
    ("name", "ok"),
    [
        (None, False),
        ("", False),
        ("   ", False),
        ("x" * 61, False),
        ("x" * 60, True),
        ("x" * 5000, False),
        ("דנה כהן", True),
        ("a​b\x00c", True),
        ("two\nlines", True),
    ],
)
def test_display_name_validation(client, name, ok):
    b = _body()
    if name is None:
        del b["display_name"]
    else:
        b["display_name"] = name
    r = client.post("/auth/register", json=b)
    assert r.status_code == (201 if ok else 422), r.text


def test_display_name_sanitised(client):
    r = client.post("/auth/register", json=_body(display_name="  a​b\x00\n c  "))
    assert r.json()["display_name"] == "ab c"
