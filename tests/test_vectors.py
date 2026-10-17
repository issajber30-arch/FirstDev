# Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform.
import time
from collections import namedtuple

import numpy as np
import pytest
from sqlalchemy import select

from firstdev.matching.vectors import from_blob, to_blob, top_k, upsert_embedding
from firstdev.models import DeveloperProfile, Embedding, OwnerKind, User

M = "m"


def test_blob_round_trip_is_float32_little_endian():
    v = [0.5, -1.25, 3.0]
    b = to_blob(v)
    assert len(b) == 12 and b[:4] == np.float32(0.5).astype("<f4").tobytes()
    assert from_blob(b, 3).tolist() == v


def test_from_blob_length_mismatch_raises():
    with pytest.raises(ValueError):
        from_blob(to_blob([1.0, 2.0]), 3)


@pytest.fixture
def profiles(db, user_factory):
    ids = []
    for i in range(3):
        u = user_factory(f"p{i}@example.com")
        ids.append(u.id)
    return ids


def put(db, pid, vec, model=M):
    return upsert_embedding(
        db, owner_kind=OwnerKind.profile, owner_id=pid, model=model, vector=vec, fingerprint="f"
    )


def q(db, vec, ids=None, k=50, model=M):
    return top_k(
        db,
        query=np.array(vec, dtype=np.float32),
        owner_kind=OwnerKind.profile,
        model=model,
        candidate_ids=ids,
        k=k,
    )


def test_top_k_orders_by_cosine(db, profiles):
    a, b, c = profiles
    put(db, a, [1, 0])
    put(db, b, [1, 1])
    put(db, c, [0, 1])
    got = q(db, [1, 0.1])
    assert [i for i, _ in got] == [a, b, c]
    assert got[0][1] > got[1][1] > got[2][1]
    assert [i for i, _ in q(db, [1, 0.1], k=2)] == [a, b]


def test_candidate_filter_and_empty_list(db, profiles):
    a, b, c = profiles
    for pid in profiles:
        put(db, pid, [1, 0])
    assert {i for i, _ in q(db, [1, 0], ids=[a, c])} == {a, c}
    assert q(db, [1, 0], ids=[]) == []


def test_zero_vector_no_nan(db, profiles):
    put(db, profiles[0], [0, 0])
    put(db, profiles[1], [1, 0])
    got = q(db, [1, 0])
    assert all(np.isfinite(s) for _, s in got)
    assert all(np.isfinite(s) for _, s in q(db, [0, 0]))


def test_dimension_mismatch_and_other_model_ignored(db, profiles):
    put(db, profiles[0], [1, 0, 0])
    put(db, profiles[1], [1, 0], model="other")
    put(db, profiles[2], [1, 0])
    assert [i for i, _ in q(db, [1, 0])] == [profiles[2]]
    assert q(db, [1, 0], model="nope") == []


def test_upsert_twice_leaves_one_row(db, profiles):
    pid = profiles[0]
    first = put(db, pid, [1, 0])
    second = put(db, pid, [0, 1])
    rows = db.scalars(select(Embedding)).all()
    assert len(rows) == 1 and first.id == second.id
    assert from_blob(rows[0].vector, rows[0].dim).tolist() == [0, 1]
    put(db, pid, [1, 1], model="other")  # a different model is a different row
    assert db.query(Embedding).count() == 2


def test_upsert_posting_twice_leaves_one_row(db, posting):
    for v in ([1, 0], [0, 1]):
        upsert_embedding(
            db,
            owner_kind=OwnerKind.posting,
            owner_id=posting.id,
            model=M,
            vector=v,
            fingerprint="f",
        )
    assert db.query(Embedding).count() == 1


def test_embeddings_cascade_on_account_and_posting_delete(db, posting, user_factory):
    u = user_factory("gone@example.com")
    put(db, u.id, [1, 0])
    upsert_embedding(
        db, owner_kind=OwnerKind.posting, owner_id=posting.id, model=M, vector=[1], fingerprint="f"
    )
    assert db.query(Embedding).count() == 2
    db.delete(db.get(User, u.id))
    db.commit()
    assert db.query(Embedding).count() == 1
    db.delete(posting)
    db.commit()
    assert db.query(Embedding).count() == 0
    assert db.get(DeveloperProfile, u.id) is None  # profile cascaded too


def test_top_k_10k_vectors_fast():
    # A stub session returns 10k stored rows, so this times the numpy path (blob decode + matmul).
    Row = namedtuple("Row", "id vector dim")
    mat = np.random.default_rng(0).standard_normal((10_000, 384)).astype(np.float32)
    rows = [Row(f"id{i}", mat[i].tobytes(), 384) for i in range(10_000)]

    class Stub:
        def execute(self, _stmt):
            return type("Res", (), {"all": lambda self: rows})()

    t = time.perf_counter()
    got = top_k(Stub(), query=mat[0], owner_kind=OwnerKind.profile, model=M, k=50)
    elapsed = time.perf_counter() - t
    assert got[0][0] == "id0" and len(got) == 50
    assert elapsed < 0.6  # spec: 200 ms, with the plan's 3x margin
