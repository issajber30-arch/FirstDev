# Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform.
"""Matching job handlers. Payloads carry ids only. (score_pair/rank_posting come in M8+.)"""

import hashlib
import logging

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from firstdev.jobs import HANDLERS
from firstdev.llm import LLM
from firstdev.matching import embeddings
from firstdev.matching.profile import build_skill_profile, posting_fingerprint
from firstdev.matching.vectors import upsert_embedding
from firstdev.models import DeveloperProfile, Embedding, Job, JobKind, JobPosting, OwnerKind

log = logging.getLogger("firstdev.match_jobs")


def _unchanged(db: Session, owner_kind: OwnerKind, col, owner_id: str, model: str, fp: str) -> bool:
    stored = db.scalars(
        select(Embedding.source_fingerprint).where(
            Embedding.owner_kind == owner_kind, col == owner_id, Embedding.model == model
        )
    ).first()
    return stored == fp


def handle_embed_profile(db: Session, job: Job, llm: LLM) -> None:
    pid = job.payload.get("profile_id")
    profile = db.get(DeveloperProfile, pid) if pid else None
    if profile is None:  # account deleted meanwhile
        return
    sp = build_skill_profile(db, profile)  # always rebuilt: cheap, and the match step needs it
    text = embeddings.profile_text(sp, profile)
    fp = hashlib.sha256(text.encode()).hexdigest()  # covers headline as well as skills and tier
    emb = embeddings.get_embedder()
    if _unchanged(db, OwnerKind.profile, Embedding.profile_id, profile.user_id, emb.model, fp):
        return
    (vec,) = emb.embed([text])
    upsert_embedding(
        db, owner_kind=OwnerKind.profile, owner_id=profile.user_id, model=emb.model,
        vector=np.asarray(vec, dtype=np.float32), fingerprint=fp,
    )  # fmt: skip
    log.info("embedded profile=%s", profile.user_id)


def handle_embed_posting(db: Session, job: Job, llm: LLM) -> None:
    pid = job.payload.get("posting_id")
    posting = db.get(JobPosting, pid) if pid else None
    if posting is None:
        return
    fp = posting_fingerprint(posting)
    emb = embeddings.get_embedder()
    if _unchanged(db, OwnerKind.posting, Embedding.posting_id, posting.id, emb.model, fp):
        return
    (vec,) = emb.embed([embeddings.posting_text(posting)])
    upsert_embedding(
        db, owner_kind=OwnerKind.posting, owner_id=posting.id, model=emb.model,
        vector=np.asarray(vec, dtype=np.float32), fingerprint=fp,
    )  # fmt: skip
    log.info("embedded posting=%s", posting.id)


HANDLERS[JobKind.embed_profile] = handle_embed_profile
HANDLERS[JobKind.embed_posting] = handle_embed_posting
