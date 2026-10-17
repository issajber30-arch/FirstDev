# Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform.
"""Matching job handlers. Payloads carry ids only. (rank_posting comes in a later milestone.)"""

import hashlib
import logging

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from firstdev.jobs import HANDLERS
from firstdev.llm import LLM
from firstdev.matching import embeddings
from firstdev.matching.explain import review_pair
from firstdev.matching.profile import build_skill_profile, posting_fingerprint
from firstdev.matching.score import apply_review, base_score
from firstdev.matching.vectors import upsert_embedding
from firstdev.models import (
    Application,
    DeveloperProfile,
    Embedding,
    Job,
    JobKind,
    JobPosting,
    MatchScore,
    OwnerKind,
    RepoAnalysis,
    Repository,
    SkillProfile,
)

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


# --- scoring -----------------------------------------------------------------------------------


def is_stale(match: MatchScore, posting: JobPosting, skill_profile: SkillProfile) -> bool:
    """A stored score is stale once the profile or the posting changed since it was computed."""
    return (
        match.profile_fingerprint != skill_profile.fingerprint
        or match.posting_fingerprint != posting_fingerprint(posting)
    )


def _repo_highlights(db: Session, profile: DeveloperProfile) -> list[dict]:
    """Latest analysis per repository, reduced to the few fields the LLM review may see."""
    out = []
    for repo in db.scalars(select(Repository).where(Repository.profile_id == profile.user_id)):
        a = db.scalars(
            select(RepoAnalysis)
            .where(RepoAnalysis.repository_id == repo.id)
            .order_by(RepoAnalysis.created_at.desc(), RepoAnalysis.id.desc())
            .limit(1)
        ).first()
        if a is None:
            continue
        out.append(
            {
                "name": f"{repo.owner}/{repo.name}",
                "complexity": a.assessment.get("complexity"),
                "summary": str(a.assessment.get("architecture_summary", ""))[:300],
                "best_practices": [
                    p["practice"]
                    for p in a.assessment.get("best_practices", [])
                    if p.get("observed")
                ],
            }
        )
    return out


def score_and_store(
    db: Session, llm: LLM, *, posting: JobPosting, profile: DeveloperProfile, explain: bool
) -> MatchScore:
    """Score one pair, reusing a fresh cached row. Flushes but never commits: if the LLM call
    fails nothing half-written survives (run_once rolls back)."""
    sp = build_skill_profile(db, profile)  # inline: the embed job may not have run yet
    ms = db.scalars(
        select(MatchScore).where(
            MatchScore.posting_id == posting.id, MatchScore.profile_id == profile.user_id
        )
    ).first()
    if ms is not None and not is_stale(ms, posting, sp) and (ms.explained or not explain):
        return ms

    eq: dict[str, str] = {}
    adjustment, reason, reasons, feedback, model = 0, "", [], {}, "formula"
    if explain:
        review, model = review_pair(llm, sp, posting, _repo_highlights(db, profile))
        eq, adjustment, reason = (
            review["equivalences"],
            review["adjustment"],
            review["adjustment_reason"],
        )
        reasons, feedback = review["reasons"], review["feedback"]
    # Recomputed with the confirmed equivalences, so components match the stored score.
    base, components = base_score(sp.skills, sp.tier, posting, eq)
    components = {**components, "equivalences": eq, "adjustment_reason": reason}
    values = dict(
        score=apply_review(base, adjustment), base_score=base, components=components,
        llm_adjustment=adjustment, reasons=reasons, feedback=feedback,
        profile_fingerprint=sp.fingerprint, posting_fingerprint=posting_fingerprint(posting),
        model=model, explained=explain,
    )  # fmt: skip
    if ms is None:
        ms = MatchScore(posting_id=posting.id, profile_id=profile.user_id, **values)
        db.add(ms)
    else:
        for k, v in values.items():
            setattr(ms, k, v)
    db.flush()
    return ms


def handle_score_pair(db: Session, job: Job, llm: LLM) -> None:
    posting = db.get(JobPosting, job.payload.get("posting_id") or "")
    profile = db.get(DeveloperProfile, job.payload.get("profile_id") or "")
    if posting is None or profile is None:  # deleted meanwhile
        return
    ms = score_and_store(
        db, llm, posting=posting, profile=profile, explain=bool(job.payload.get("explain"))
    )
    app = db.get(Application, job.payload.get("application_id") or "")
    if app is not None and app.job_posting_id == posting.id and app.profile_id == profile.user_id:
        app.match_score_id = ms.id
    db.commit()
    log.info(
        "scored posting=%s profile=%s score=%d explained=%s",
        posting.id,
        profile.user_id,
        ms.score,
        ms.explained,
    )


HANDLERS[JobKind.score_pair] = handle_score_pair
HANDLERS[JobKind.embed_profile] = handle_embed_profile
HANDLERS[JobKind.embed_posting] = handle_embed_posting
