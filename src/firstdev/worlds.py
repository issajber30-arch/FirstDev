# Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform.
"""World isolation: real users (world_id NULL) and each sandbox world never see one another.

Every query that returns or matches ANOTHER user's data must go through `same_world`.
"""

from sqlalchemy import Select, select
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from firstdev.models import User


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
