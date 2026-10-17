# Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform.
"""Global daily LLM spend cap: reserve the worst case before a call, settle (or release) after.

Every function opens its OWN session from `db_factory` and commits immediately, so a reservation
is visible to concurrent workers at once and survives a rollback of the calling handler.
"""

import logging
from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from firstdev.config import get_settings
from firstdev.llm import LLMContext, LLMPermanentError, cost_usd
from firstdev.models import LedgerStatus, LlmLedger

log = logging.getLogger("firstdev.budget")

DbFactory = Callable[[], Session]
# Permanent on purpose: retrying a job cannot help until the UTC day rolls over.
MESSAGE = "demo AI budget reached for today"


class BudgetExceeded(LLMPermanentError):
    def __init__(self) -> None:
        super().__init__(MESSAGE)


def estimate_worst_usd(system: str, content: str, max_tokens: int) -> float:
    """Pessimistic cost: ~3 characters per input token, and the full max_tokens as output."""
    return cost_usd(None, (len(system) + len(content)) // 3 + 1, max_tokens)


def _today_total(db: Session, day) -> float:
    return float(
        db.scalar(
            select(
                func.coalesce(
                    func.sum(func.coalesce(LlmLedger.actual_usd, LlmLedger.reserved_usd)), 0.0
                )
            ).where(LlmLedger.day == day, LlmLedger.status != LedgerStatus.released)
        )
        or 0.0
    )


def reserve(
    db_factory: DbFactory, ctx: LLMContext, worst_usd: float, *, now: datetime | None = None
) -> str:
    """Insert a `reserved` row and return its id, or raise BudgetExceeded (nothing inserted)."""
    now = now or datetime.now(UTC)
    cap = get_settings().llm_daily_usd
    with db_factory() as db:
        if db.get_bind().dialect.name == "sqlite":
            # shortcut: BEGIN IMMEDIATE takes SQLite's single write lock before the read, so
            # check-then-insert is serialized across threads and processes. Postgres needs a row
            # lock (SELECT ... FOR UPDATE on a budget row); that comes with Part 6.
            db.execute(text("BEGIN IMMEDIATE"))
        if _today_total(db, now.date()) + worst_usd > cap:
            db.rollback()
            raise BudgetExceeded
        row = LlmLedger(
            day=now.date(),
            user_id=ctx.user_id,
            world_id=ctx.world_id,
            kind=ctx.kind,
            reserved_usd=worst_usd,
            status=LedgerStatus.reserved,
        )
        db.add(row)
        db.commit()
        return row.id


def settle(db_factory: DbFactory, ledger_id: str, usage) -> None:
    """Record the real cost; `usage` needs .model, .input_tokens and .output_tokens."""
    with db_factory() as db:
        row = db.get(LlmLedger, ledger_id)
        if row is None:  # user-independent row, but the sweep may have removed it
            return
        row.actual_usd = cost_usd(usage.model, usage.input_tokens, usage.output_tokens)
        row.status = LedgerStatus.settled
        db.commit()


def release(db_factory: DbFactory, ledger_id: str) -> None:
    """The call produced no cost: stop counting the reservation."""
    with db_factory() as db:
        row = db.get(LlmLedger, ledger_id)
        if row is not None and row.status == LedgerStatus.reserved:
            row.status = LedgerStatus.released
            db.commit()
