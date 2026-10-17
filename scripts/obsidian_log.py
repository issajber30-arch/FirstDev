# Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform.
"""Write a progress note into the Obsidian vault. Stdlib only; never fails a commit."""

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path

KEY = "FIRSTDEV_OBSIDIAN_LOG_DIR"
ROOT = Path(__file__).resolve().parent.parent


def log_dir() -> str | None:
    """Env var wins; otherwise read the project .env (simple KEY=VALUE lines)."""
    if os.environ.get(KEY):
        return os.environ[KEY]
    try:
        for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
            name, sep, value = line.strip().partition("=")
            if sep and name.strip() == KEY:
                return value.strip().strip("\"'") or None
    except OSError:
        pass
    return None


def safe_title(title: str) -> str:
    """Keep letters (any script), digits, space, - and _; everything else becomes -."""
    cleaned = "".join(c if c.isalnum() or c in " -_" else "-" for c in title)
    # No dots survive, so ".." and path separators cannot appear.
    return cleaned.strip()[:80].strip() or "untitled"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--title", required=True)
    p.add_argument("--body", required=True)
    p.add_argument("--kind", choices=["commit", "milestone", "decision"], default="commit")
    args = p.parse_args(argv)

    directory = log_dir()
    if not directory or not Path(directory).is_dir():
        print(f"obsidian_log: {KEY} unset or not a directory; skipping note", file=sys.stderr)
        return 0

    now = datetime.now()
    base = f"{now:%Y-%m-%d %H%M%S} {args.kind} - {safe_title(args.title)}"
    # Title lives only in the (sanitized) filename, so it can't break the frontmatter.
    text = (
        f"---\ndate: {now:%Y-%m-%d %H:%M:%S}\nkind: {args.kind}\nproject: FirstDev\n"
        "author: Issa Jber\n"
        "copyright: (c) 2026 Issa Jber. All rights reserved.\n"
        f"tags: [firstdev, {args.kind}]\n---\n\n{args.body}\n"
    )
    n = 0
    while True:
        name = f"{base}.md" if n == 0 else f"{base} ({n}).md"
        try:
            # Mode "x" fails if the file exists, so a note is never overwritten.
            with open(Path(directory) / name, "x", encoding="utf-8") as f:
                f.write(text)
            return 0
        except FileExistsError:
            n += 1
        except OSError as e:
            print(f"obsidian_log: could not write note: {e}", file=sys.stderr)
            return 0


if __name__ == "__main__":
    sys.exit(main())
