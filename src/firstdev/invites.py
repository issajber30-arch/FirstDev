# Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform.
"""Single-use invite codes for real signups. Only the sha256 is stored; the code is shown once."""

import hashlib
import secrets
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from firstdev.models import InviteCode

# 32 symbols, no I/O/0/1: 12 characters give 60 bits (spec says 31/59; its string has 32).
ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
LENGTH = 12


def generate_code() -> str:
    raw = "".join(secrets.choice(ALPHABET) for _ in range(LENGTH))
    return "-".join(raw[i : i + 4] for i in range(0, LENGTH, 4))


def hash_code(code: str) -> str:
    """Hash after normalising: case, dashes and spaces never matter."""
    norm = "".join(code.upper().replace("-", "").split())
    return hashlib.sha256(norm.encode()).hexdigest()


def create(db: Session, label: str) -> str:
    code = generate_code()
    db.add(InviteCode(code_hash=hash_code(code), label=label))
    db.commit()
    return code


def consume(db: Session, code: str) -> InviteCode | None:
    """Atomically mark an unused, unrevoked code used; None if it can't be (not committed)."""
    row = db.scalar(select(InviteCode).where(InviteCode.code_hash == hash_code(code)))
    if row is None:
        return None
    claimed = db.execute(
        update(InviteCode)
        .where(
            InviteCode.id == row.id, InviteCode.used_at.is_(None), InviteCode.revoked_at.is_(None)
        )
        .values(used_at=datetime.now(UTC))
    )
    return row if claimed.rowcount == 1 else None


def status(row: InviteCode) -> str:
    return "used" if row.used_at else "revoked" if row.revoked_at else "unused"
