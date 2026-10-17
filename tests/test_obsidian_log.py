import os
import subprocess
import sys
from pathlib import Path

import obsidian_log

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "obsidian_log.py"


def run(log_dir, title, body="b", kind="commit"):
    env = {**os.environ, "FIRSTDEV_OBSIDIAN_LOG_DIR": str(log_dir)}
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--title", title, "--body", body, "--kind", kind],
        env=env,
        capture_output=True,
        text=True,
    )


def test_writes_note(tmp_path):
    r = run(tmp_path, "hello", "body text")
    assert r.returncode == 0
    (note,) = tmp_path.glob("* commit - hello.md")
    text = note.read_text(encoding="utf-8")
    assert text.startswith("---\n") and "project: FirstDev" in text and "body text" in text


def test_title_sanitized(tmp_path):
    r = run(tmp_path, "../../etc/passwd")
    assert r.returncode == 0
    (note,) = tmp_path.iterdir()
    assert "/" not in note.name and ".." not in note.name
    assert note.parent == tmp_path


def test_safe_title_limits():
    assert len(obsidian_log.safe_title("a" * 500)) <= 80
    assert obsidian_log.safe_title("///") == "---"
    assert obsidian_log.safe_title("") == "untitled"


def test_hebrew_kept(tmp_path):
    run(tmp_path, "שלום עולם")
    assert any("שלום עולם" in p.name for p in tmp_path.iterdir())


def test_missing_dir_exits_zero(tmp_path):
    missing = tmp_path / "nope"
    r = run(missing, "x")
    assert r.returncode == 0
    assert "skipping" in r.stderr
    assert not missing.exists()


def test_no_overwrite(tmp_path, monkeypatch):
    monkeypatch.setenv("FIRSTDEV_OBSIDIAN_LOG_DIR", str(tmp_path))
    frozen = obsidian_log.datetime.now()

    class Fixed(obsidian_log.datetime):
        @classmethod
        def now(cls, tz=None):
            return frozen

    monkeypatch.setattr(obsidian_log, "datetime", Fixed)
    for _ in range(2):
        obsidian_log.main(["--title", "same", "--body", "b"])
    assert len(list(tmp_path.iterdir())) == 2
