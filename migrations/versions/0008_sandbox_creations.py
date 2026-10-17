# Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform.
"""sandbox creations

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-17 20:00:54.284281

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0008"
down_revision: str | Sequence[str] | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "sandbox_creations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("ip_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sandbox_creations")),
    )
    with op.batch_alter_table("sandbox_creations", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_sandbox_creations_ip_hash"), ["ip_hash"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("sandbox_creations", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_sandbox_creations_ip_hash"))

    op.drop_table("sandbox_creations")
