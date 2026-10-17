# Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform.
import hashlib
import json
import subprocess  # noqa: S404
import sys
from dataclasses import dataclass
from typing import Literal

PDF_MAX = 5 * 1024 * 1024
TEXT_MAX = 200 * 1024
# Worker output is at most max_chars of text, JSON-escaped (worst case 6x for \uXXXX).
_STDOUT_CAP = 2 * 1024 * 1024


class UploadRejected(ValueError):
    pass


@dataclass(frozen=True)
class UploadInfo:
    kind: Literal["pdf", "text"]
    size: int
    sha256: str


@dataclass(frozen=True)
class PdfText:
    text: str
    page_count: int


def validate_upload(data: bytes, *, kind_hint: str | None) -> UploadInfo:
    """Classify by content only; filename and content-type (kind_hint) are never trusted."""
    if not data:
        raise UploadRejected("empty file")
    if data.startswith(b"%PDF-"):
        kind, limit = "pdf", PDF_MAX
    else:
        kind, limit = "text", TEXT_MAX
    if len(data) > limit:
        raise UploadRejected(f"{kind} file too large")
    if kind == "text":
        try:
            data.decode("utf-8")
        except UnicodeDecodeError:
            raise UploadRejected("unsupported file type") from None
        if b"\x00" in data:
            raise UploadRejected("unsupported file type")
    return UploadInfo(kind, len(data), hashlib.sha256(data).hexdigest())


def extract_pdf_text(
    data: bytes, *, timeout_s: float = 20, max_pages: int = 10, max_chars: int = 200_000
) -> PdfText:
    cmd = [
        sys.executable,
        "-I",
        "-m",
        "firstdev.security._pdf_worker",
        str(max_pages),
        str(max_chars),
    ]
    try:
        # Isolated child: a parser hang or crash cannot take down the API/worker process.
        proc = subprocess.Popen(  # noqa: S603
            cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
    except OSError:
        raise UploadRejected("pdf processing failed") from None
    try:
        # communicate() buffers fully, so the size cap is enforced after the read; the CPU
        # limit and timeout bound how much a worker can emit.
        out, _err = proc.communicate(data, timeout=timeout_s)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate()
        raise UploadRejected("pdf processing timed out") from None
    if proc.returncode != 0 or len(out) > _STDOUT_CAP:
        raise UploadRejected("pdf processing failed")
    try:
        res = json.loads(out)
        ok, text, pages = bool(res["ok"]), str(res["text"]), int(res["pages"])
        error = res["error"]
    except (ValueError, KeyError, TypeError):
        raise UploadRejected("pdf processing failed") from None
    if not ok:
        raise UploadRejected(str(error) if error in _ERRORS else "pdf processing failed")
    return PdfText(text, pages)


# Only our own worker messages are passed through to callers.
_ERRORS = {"encrypted pdf", "too many pages", "extracted text too large", "unreadable pdf"}
