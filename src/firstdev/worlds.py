# Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform.
"""World isolation: real users (world_id NULL) and each sandbox world never see one another.

Every query that returns or matches ANOTHER user's data must go through `same_world`.
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import Select, delete, select, update
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from firstdev.models import LlmLedger, SandboxCreation, User


def _world_cond(caller: User) -> ColumnElement[bool]:
    return User.world_id.is_(None) if caller.world_id is None else User.world_id == caller.world_id


def same_world[S: Select](stmt: S, user_col, caller: User) -> S:
    """Restrict `stmt` to rows whose `user_col` (a users.id value) lives in the caller's world.

    An IN-subquery rather than a join: it composes with statements that already join users
    and never changes the row shape.
    """
    return stmt.where(user_col.in_(select(User.id).where(_world_cond(caller))))


def in_world(db: Session, user_id: str, caller: User) -> bool:
    return db.scalar(select(User.id).where(User.id == user_id, _world_cond(caller))) is not None


def delete_worlds(db: Session, world_ids: set[str]) -> None:
    """Delete every user of the given sandbox worlds (the database cascades to all their rows).
    The budget ledger keeps its rows (spend is still spend); only the world link is dropped."""
    if not world_ids:
        return
    db.execute(delete(User).where(User.world_id.in_(world_ids)))
    db.execute(update(LlmLedger).where(LlmLedger.world_id.in_(world_ids)).values(world_id=None))
    db.commit()


def sweep_expired(db: Session, *, now: datetime | None = None) -> int:
    """Delete sandbox worlds whose users have expired; returns the number of worlds removed.
    Also prunes per-IP creation rows older than the 24 h limit window (they can no longer count).
    Handlers no-op on rows that vanished mid-job, so a running job is never a reason to wait."""
    now = now or datetime.now(UTC)
    worlds = set(
        db.scalars(
            select(User.world_id)
            .where(User.expires_at < now, User.world_id.is_not(None))
            .distinct()
        )
    )
    delete_worlds(db, worlds)
    db.execute(delete(User).where(User.expires_at < now))  # defensive: expired without a world
    db.execute(
        delete(SandboxCreation).where(SandboxCreation.created_at < now - timedelta(hours=24))
    )
    db.commit()
    return len(worlds)
