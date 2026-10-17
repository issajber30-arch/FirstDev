# Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform.
"""Text embeddings. Only the worker ever embeds; the API reads stored vectors."""

import hashlib
import math
import re
from functools import lru_cache
from pathlib import Path
from typing import Protocol

from firstdev.config import get_settings
from firstdev.errors import TransientError
from firstdev.models import DeveloperProfile, JobPosting, SkillProfile

MODEL_NAME = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
_POSTING_DESC_CHARS = 2000


class EmbeddingUnavailable(TransientError):
    """The model could not be loaded or run (e.g. the download failed); the job retries."""


class Embedder(Protocol):
    model: str
    dim: int

    def embed(self, texts: list[str]) -> list[list[float]]: ...


class FastEmbedder:
    """fastembed (ONNX) model, loaded lazily on the first embed() call."""

    dim = 384

    def __init__(self, model: str = MODEL_NAME):
        self.model = model
        self._engine = None

    def embed(self, texts: list[str]) -> list[list[float]]:
        try:
            if self._engine is None:
                from fastembed import TextEmbedding  # imported here so API startup stays light

                cache = Path(get_settings().model_cache).expanduser()
                self._engine = TextEmbedding(self.model, cache_dir=str(cache))
            return [[float(x) for x in v] for v in self._engine.embed(texts)]
        except Exception:
            # Never echo the underlying message: it can contain URLs and local paths.
            raise EmbeddingUnavailable("embedding model unavailable") from None


class FakeEmbedder:
    """Test double: bag-of-words hashed into `dim` buckets, L2-normalized."""

    model = "fake-embedder"

    def __init__(self, dim: int = 8):
        self.dim = dim
        self.calls = 0  # number of embed() calls, for skip-if-unchanged tests

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls += 1
        out = []
        for text in texts:
            v = [0.0] * self.dim
            for tok in re.findall(r"\w+", text.casefold()):
                h = int.from_bytes(hashlib.sha256(tok.encode()).digest()[:8], "big")
                v[h % self.dim] += 1.0
            norm = math.sqrt(sum(x * x for x in v))
            out.append([x / norm for x in v] if norm else v)
        return out


@lru_cache
def get_embedder() -> Embedder:
    """Provider so tests can replace it, like get_llm. Constructing loads nothing."""
    return FastEmbedder()


def profile_text(skill_profile: SkillProfile, profile: DeveloperProfile) -> str:
    """Headline, tier and skill names only: no names, contacts, education, gaps or sources."""
    names = " ".join(e["skill"] for e in skill_profile.skills)
    return f"{profile.headline or ''}\n{skill_profile.tier}\n{names}".strip()


def posting_text(posting: JobPosting) -> str:
    req = " ".join(posting.required_skills or [])
    opt = " ".join(posting.optional_skills or [])
    return f"{posting.title}\n{req}\n{opt}\n{posting.description[:_POSTING_DESC_CHARS]}"
