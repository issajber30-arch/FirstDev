import os
import subprocess
from pathlib import Path

import pytest

HOOK = Path(__file__).resolve().parent.parent / ".githooks" / "pre-commit"


@pytest.fixture
def repo(tmp_path):
    for cmd in (["init", "-q"], ["config", "user.email", "t@t"], ["config", "user.name", "t"]):
        subprocess.run(["git", *cmd], cwd=tmp_path, check=True)
    return tmp_path


def stage_and_run(repo, name, content):
    (repo / name).write_text(content)
    subprocess.run(["git", "add", "-f", name], cwd=repo, check=True)
    return subprocess.run(
        ["sh", str(HOOK)],
        cwd=repo,
        env={**os.environ, "SKIP_RUFF": "1"},
        capture_output=True,
        text=True,
    )


def test_blocks_secret(repo):
    r = stage_and_run(repo, "a.txt", "key = sk-ant-" + "A" * 20 + "\n")
    assert r.returncode != 0
    assert "a.txt" in r.stderr


def test_blocks_private_key(repo):
    r = stage_and_run(repo, "k.pem", "-----BEGIN RSA " + "PRIVATE KEY-----\n")
    assert r.returncode != 0


def test_blocks_env_file(repo):
    r = stage_and_run(repo, ".env", "X=1\n")
    assert r.returncode != 0


def test_allows_env_example(repo):
    assert stage_and_run(repo, ".env.example", "X=\n").returncode == 0


def test_clean_file_passes(repo):
    assert stage_and_run(repo, "ok.txt", "hello\n").returncode == 0
