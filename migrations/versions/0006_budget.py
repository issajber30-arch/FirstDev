# Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform.
"""budget

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-17 19:36:14.585091

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0006"
down_revision: str | Sequence[str] | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "llm_ledger",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=True),
        sa.Column("world_id", sa.String(length=36), nullable=True),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("reserved_usd", sa.Float(), nullable=False),
        sa.Column("actual_usd", sa.Float(), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "reserved",
                "settled",
                "released",
                name="ledger_status",
                native_enum=False,
                create_constraint=False,
                length=20,
            ),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('reserved', 'settled', 'released')",
            name=op.f("ck_llm_ledger_ledger_status"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_llm_ledger_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_llm_ledger")),
    )
    with op.batch_alter_table("llm_ledger", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_llm_ledger_day"), ["day"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("llm_ledger", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_llm_ledger_day"))

    op.drop_table("llm_ledger")
