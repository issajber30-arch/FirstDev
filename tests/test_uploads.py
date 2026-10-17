# Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform.
import io

import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from firstdev.security import uploads
from firstdev.security.uploads import UploadRejected, extract_pdf_text, validate_upload

MB5 = 5 * 1024 * 1024


def make_pdf(pages: int = 1, text: str | None = "Hello FirstDev", password: str | None = None):
    w = PdfWriter()
    for _ in range(pages):
        page = w.add_blank_page(200, 200)
        if text:
            font = DictionaryObject(
                {
                    NameObject("/Type"): NameObject("/Font"),
                    NameObject("/Subtype"): NameObject("/Type1"),
                    NameObject("/BaseFont"): NameObject("/Helvetica"),
                }
            )
            page[NameObject("/Resources")] = DictionaryObject(
                {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})}
            )
            stream = DecodedStreamObject()
            stream.set_data(f"BT /F1 12 Tf 20 100 Td ({text}) Tj ET".encode())
            page[NameObject("/Contents")] = w._add_object(stream)
    if password:
        w.encrypt(password)
    buf = io.BytesIO()
    w.write(buf)
    return buf.getvalue()


def test_empty():
    with pytest.raises(UploadRejected, match="empty file"):
        validate_upload(b"", kind_hint=None)


def test_pdf_size_boundary():
    ok = validate_upload(b"%PDF-" + b"a" * (MB5 - 5), kind_hint=None)
    assert ok.kind == "pdf" and ok.size == MB5 and len(ok.sha256) == 64
    with pytest.raises(UploadRejected):
        validate_upload(b"%PDF-" + b"a" * (MB5 - 4), kind_hint=None)


def test_text_boundary_and_hint_ignored():
    assert validate_upload(b"a" * 200 * 1024, kind_hint="pdf").kind == "text"
    with pytest.raises(UploadRejected):
        validate_upload(b"a" * (200 * 1024 + 1), kind_hint="text")


def test_binary_and_nul_rejected():
    for data in (b"\xff\xfe\x00\x80", b"abc\x00def"):
        with pytest.raises(UploadRejected, match="unsupported file type"):
            validate_upload(data, kind_hint=None)


def test_pdf_named_text_is_text():
    assert validate_upload(b"hello cv", kind_hint="application/pdf").kind == "text"


def test_real_pdf_extracts():
    r = extract_pdf_text(make_pdf(2))
    assert r.page_count == 2 and "Hello FirstDev" in r.text


def test_blank_pdf_gives_empty_text():
    r = extract_pdf_text(make_pdf(text=None))
    assert r.text.strip() == "" and r.page_count == 1


def test_encrypted_rejected():
    with pytest.raises(UploadRejected, match="encrypted"):
        extract_pdf_text(make_pdf(password="pw"))


def test_too_many_pages():
    assert extract_pdf_text(make_pdf(10)).page_count == 10
    with pytest.raises(UploadRejected, match="too many pages"):
        extract_pdf_text(make_pdf(11))


def test_text_too_large():
    with pytest.raises(UploadRejected, match="too large"):
        extract_pdf_text(make_pdf(text="x" * 50), max_chars=10)


def test_garbage_generic_error():
    for data in (b"%PDF-1.4\ngarbage", make_pdf()[:100]):
        with pytest.raises(UploadRejected, match="unreadable pdf"):
            extract_pdf_text(data)


def test_timeout(monkeypatch):
    real_popen = uploads.subprocess.Popen
    sleeper = [uploads.sys.executable, "-c", "import time; time.sleep(30)"]
    monkeypatch.setattr(uploads.subprocess, "Popen", lambda _cmd, **kw: real_popen(sleeper, **kw))
    with pytest.raises(UploadRejected, match="timed out"):
        extract_pdf_text(make_pdf(), timeout_s=0.3)
