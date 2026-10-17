# Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform.
"""Offline tests for the safety gates of scripts/e2e_smoke.py (no servers, no network)."""

import os
import subprocess
import sys

from conftest import ROOT

SCRIPT = ROOT / "scripts" / "e2e_smoke.py"


def run(args, env_extra=None, tmp_path=None):
    env = {k: v for k, v in os.environ.items() if k not in ("ANTHROPIC_API_KEY", "GITHUB_TOKEN")}
    env.update(env_extra or {})
    return subprocess.run(  # noqa: S603 - fixed argv, no shell
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        env=env,
        cwd=tmp_path,
        timeout=30,
    )


def test_refuses_without_yes(tmp_path):
    r = run([], tmp_path=tmp_path)
    assert r.returncode == 2
    assert "a few cents" in r.stdout
    assert "PASS" not in r.stdout  # nothing ran


def test_missing_keys_listed_without_values(tmp_path):
    empty = tmp_path / "empty.env"
    empty.write_text("")
    r = run(["--yes", "--env-file", str(empty)], tmp_path=tmp_path)
    assert r.returncode == 2
    assert "ANTHROPIC_API_KEY" in r.stderr
    assert "PASS" not in r.stdout


def test_only_absent_key_is_named_and_values_never_printed(tmp_path):
    f = tmp_path / "x.env"
    f.write_text("GITHUB_TOKEN=ghp-secret-value-123\n")
    r = run(["--yes", "--env-file", str(f)], tmp_path=tmp_path)
    assert r.returncode == 2
    assert "ANTHROPIC_API_KEY" in r.stderr and "GITHUB_TOKEN" not in r.stderr
    assert "ghp-secret-value-123" not in r.stdout + r.stderr
