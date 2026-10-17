# Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform.
"""PDF text extraction, run as a child process: PDF bytes on stdin, one JSON object on stdout."""

import io
import json
import sys

try:
    import resource
except ImportError:  # pragma: no cover  (non-POSIX)
    resource = None

MAX_PAGES = 10
MAX_CHARS = 200_000
CPU_SECONDS = 20


def _result(ok: bool, error: str | None = None, text: str = "", pages: int = 0) -> None:
    sys.stdout.write(json.dumps({"ok": ok, "error": error, "text": text, "pages": pages}))


def main() -> None:
    max_pages = int(sys.argv[1]) if len(sys.argv) > 1 else MAX_PAGES
    max_chars = int(sys.argv[2]) if len(sys.argv) > 2 else MAX_CHARS
    try:
        # shortcut: macOS ignores RLIMIT_AS, so memory is bounded only by timeout; add a
        # container memory limit at deploy.
        resource.setrlimit(resource.RLIMIT_CPU, (CPU_SECONDS, CPU_SECONDS))
    except Exception:  # noqa: S110  (best effort: unsupported on some platforms)
        pass
    data = sys.stdin.buffer.read()
    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            return _result(False, "encrypted pdf")
        pages = len(reader.pages)
        if pages > max_pages:
            return _result(False, "too many pages", pages=pages)
        parts: list[str] = []
        total = 0
        for page in reader.pages:
            t = page.extract_text() or ""
            parts.append(t)
            total += len(t)
            if total > max_chars:
                return _result(False, "extracted text too large", pages=pages)
        _result(True, text="\n".join(parts), pages=pages)
    except Exception:
        _result(False, "unreadable pdf")  # never echo parser internals


if __name__ == "__main__":
    main()
