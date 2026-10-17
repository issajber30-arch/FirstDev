# Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform.
"""Vector storage in SQLite (float32 little-endian BLOBs) and numpy cosine search."""

from collections.abc import Sequence

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from firstdev.models import Embedding, OwnerKind


def to_blob(vec: Sequence[float] | np.ndarray) -> bytes:
    return np.asarray(vec, dtype="<f4").tobytes()


def from_blob(b: bytes, dim: int) -> np.ndarray:
    if len(b) != dim * 4:
        raise ValueError("vector blob length does not match dim")
    return np.frombuffer(b, dtype="<f4").astype(np.float32)


def _owner_col(owner_kind: OwnerKind):
    return Embedding.profile_id if owner_kind == OwnerKind.profile else Embedding.posting_id


def upsert_embedding(
    db: Session,
    *,
    owner_kind: OwnerKind,
    owner_id: str,
    model: str,
    vector: Sequence[float] | np.ndarray,
    fingerprint: str,
) -> Embedding:
    # Look the row up ourselves: the table's unique constraint cannot catch duplicates in SQLite
    # because the other owner column is NULL (and NULLs are distinct).
    row = db.scalars(
        select(Embedding).where(
            Embedding.owner_kind == owner_kind,
            _owner_col(owner_kind) == owner_id,
            Embedding.model == model,
        )
    ).first()
    if row is None:
        row = Embedding(owner_kind=owner_kind, model=model)
        setattr(row, "profile_id" if owner_kind == OwnerKind.profile else "posting_id", owner_id)
        db.add(row)
    row.dim = len(vector)
    row.vector = to_blob(vector)
    row.source_fingerprint = fingerprint
    db.commit()
    return row


def top_k(
    db: Session,
    *,
    query: np.ndarray,
    owner_kind: OwnerKind,
    model: str,
    candidate_ids: list[str] | None = None,
    k: int = 50,
) -> list[tuple[str, float]]:
    col = _owner_col(owner_kind)
    stmt = select(col, Embedding.vector, Embedding.dim).where(
        Embedding.owner_kind == owner_kind, Embedding.model == model
    )
    if candidate_ids is not None:
        if not candidate_ids:
            return []
        stmt = stmt.where(col.in_(candidate_ids))
    rows = db.execute(stmt).all()
    rows = [r for r in rows if r.dim == query.shape[0]]  # ignore vectors from another model size
    if not rows:
        return []
    mat = np.stack([from_blob(r.vector, r.dim) for r in rows])
    q = query / (np.linalg.norm(query) or 1.0)
    norms = np.linalg.norm(mat, axis=1)
    norms[norms == 0] = 1.0
    sims = (mat @ q) / norms
    order = np.argsort(-sims)[:k]
    return [(rows[i][0], float(sims[i])) for i in order]
