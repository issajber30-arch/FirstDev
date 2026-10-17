# Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform.
import importlib
import subprocess
import sys

import numpy as np
import pytest

from firstdev.errors import TransientError
from firstdev.matching.embeddings import (
    EmbeddingUnavailable,
    FakeEmbedder,
    FastEmbedder,
    posting_text,
    profile_text,
)
from firstdev.models import JobPosting, SkillProfile, Tier


def cos(a, b):
    return float(np.dot(a, b))


def test_fake_embedder_deterministic_normalized():
    e = FakeEmbedder()
    a1, a2 = e.embed(["python fastapi", "python fastapi"])
    assert a1 == a2 and len(a1) == e.dim == 8
    assert abs(np.linalg.norm(a1) - 1) < 1e-6
    assert FakeEmbedder().embed(["python fastapi"])[0] == a1


def test_fake_embedder_shared_words_are_closer():
    e = FakeEmbedder(dim=64)
    base, near, far = e.embed(["python fastapi docker", "python fastapi redis", "cobol fortran"])
    assert cos(base, near) > cos(base, far)
    assert e.embed([""])[0] == [0.0] * 64  # empty text: zero vector, no NaN


def test_profile_text_has_no_pii(db, profile):
    profile.headline = "Backend dev"
    profile.bio = "my secret bio jane@example.com"
    profile.location = "Tel Aviv"
    sp = SkillProfile(
        profile_id=profile.user_id,
        skills=[{"skill": "python", "level": "repo", "years": 3, "sources": ["o/r"]}],
        tier=Tier.mid,
        fingerprint="f",
    )
    text = profile_text(sp, profile)
    assert "Backend dev" in text and "mid" in text and "python" in text
    for banned in ("dev@example.com", "jane@example.com", "secret bio", "Tel Aviv", "gap", "o/r"):
        assert banned not in text


def test_posting_text_truncates_description():
    p = JobPosting(
        title="Eng",
        description="x" * 5000,
        required_skills=["python"],
        optional_skills=["go"],
    )
    t = posting_text(p)
    assert "Eng" in t and "python" in t and "go" in t
    assert t.count("x") == 2000


def test_fast_embedder_failure_is_transient(monkeypatch):
    import fastembed

    def boom(*a, **k):
        raise OSError("download failed: secret-url")

    monkeypatch.setattr(fastembed, "TextEmbedding", boom)
    with pytest.raises(EmbeddingUnavailable) as ei:
        FastEmbedder().embed(["hi"])
    assert isinstance(ei.value, TransientError)
    assert "secret-url" not in str(ei.value)


def test_fast_embedder_is_lazy(monkeypatch):
    import fastembed

    def boom(*a, **k):
        raise AssertionError("model constructed")

    monkeypatch.setattr(fastembed, "TextEmbedding", boom)
    e = FastEmbedder()  # constructing must not load anything
    assert e.dim == 384


def test_import_never_constructs_the_model(monkeypatch):
    import fastembed

    def boom(*a, **k):
        raise AssertionError("model constructed at import")

    monkeypatch.setattr(fastembed, "TextEmbedding", boom)
    for name in (
        "firstdev.matching.embeddings",
        "firstdev.matching.vectors",
        "firstdev.pipelines.match_jobs",
        "firstdev.worker",
        "firstdev.app",
    ):
        importlib.reload(importlib.import_module(name))


def test_api_process_never_imports_fastembed():
    code = "import sys, firstdev.app; sys.exit('fastembed' in sys.modules)"
    r = subprocess.run(  # noqa: S603
        [sys.executable, "-I", "-c", code],
        env={"FIRSTDEV_JWT_SECRET": "x" * 40},
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 0, r.stderr
