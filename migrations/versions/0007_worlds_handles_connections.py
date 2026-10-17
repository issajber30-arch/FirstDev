# Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform.
"""worlds, handles and connections

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-17 19:50:21.462736

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0007"
down_revision: str | Sequence[str] | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # Autogenerate does not see CHECK changes: widen connections.status for 'removed'.
    with op.batch_alter_table("connections", schema=None) as batch_op:
        batch_op.add_column(sa.Column("responded_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.drop_constraint(batch_op.f("ck_connections_connection_status"), type_="check")
        batch_op.create_check_constraint(
            batch_op.f("ck_connections_connection_status"),
            "status IN ('pending', 'accepted', 'declined', 'removed')",
        )

    # world_id NULL = the real world; existing users stay there. handle is unique (NULLs repeat).
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.add_column(sa.Column("world_id", sa.String(length=36), nullable=True))
        batch_op.add_column(sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("handle", sa.String(length=30), nullable=True))
        batch_op.add_column(
            sa.Column("public_profile", sa.Boolean(), server_default=sa.text("0"), nullable=False)
        )
        batch_op.create_index(batch_op.f("ix_users_world_id"), ["world_id"], unique=False)
        batch_op.create_unique_constraint(batch_op.f("uq_users_handle"), ["handle"])


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_constraint(batch_op.f("uq_users_handle"), type_="unique")
        batch_op.drop_index(batch_op.f("ix_users_world_id"))
        batch_op.drop_column("public_profile")
        batch_op.drop_column("handle")
        batch_op.drop_column("expires_at")
        batch_op.drop_column("world_id")

    # Removed connections would violate the narrowed CHECK.
    op.execute("DELETE FROM connections WHERE status = 'removed'")
    with op.batch_alter_table("connections", schema=None) as batch_op:
        batch_op.drop_constraint(batch_op.f("ck_connections_connection_status"), type_="check")
        batch_op.create_check_constraint(
            batch_op.f("ck_connections_connection_status"),
            "status IN ('pending', 'accepted', 'declined')",
        )
        batch_op.drop_column("responded_at")
