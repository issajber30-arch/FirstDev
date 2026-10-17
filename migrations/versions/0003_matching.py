# Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform.
"""matching

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-17 15:46:38.011295

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # Autogenerate does not see CHECK changes: widen jobs.kind for the new job kinds.
    with op.batch_alter_table("jobs", schema=None) as batch_op:
        batch_op.drop_constraint(batch_op.f("ck_jobs_job_kind"), type_="check")
        batch_op.create_check_constraint(
            batch_op.f("ck_jobs_job_kind"),
            "kind IN ('cv_parse', 'repo_analyze', 'embed_profile', 'embed_posting', 'score_pair', 'rank_posting')",
        )

    op.create_table(
        "embeddings",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column(
            "owner_kind",
            sa.Enum(
                "profile",
                "posting",
                name="owner_kind",
                native_enum=False,
                create_constraint=False,
                length=20,
            ),
            nullable=False,
        ),
        sa.Column("profile_id", sa.String(length=36), nullable=True),
        sa.Column("posting_id", sa.String(length=36), nullable=True),
        sa.Column("model", sa.String(length=100), nullable=False),
        sa.Column("dim", sa.Integer(), nullable=False),
        sa.Column("vector", sa.LargeBinary(), nullable=False),
        sa.Column("source_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "(profile_id IS NULL) != (posting_id IS NULL) AND ((owner_kind = 'profile' AND profile_id IS NOT NULL) OR (owner_kind = 'posting' AND posting_id IS NOT NULL))",
            name=op.f("ck_embeddings_one_owner"),
        ),
        sa.CheckConstraint(
            "owner_kind IN ('profile', 'posting')", name=op.f("ck_embeddings_owner_kind")
        ),
        sa.ForeignKeyConstraint(
            ["posting_id"],
            ["job_postings.id"],
            name=op.f("fk_embeddings_posting_id_job_postings"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["profile_id"],
            ["developer_profiles.user_id"],
            name=op.f("fk_embeddings_profile_id_developer_profiles"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_embeddings")),
        sa.UniqueConstraint(
            "owner_kind", "profile_id", "posting_id", "model", name=op.f("uq_embeddings_owner_kind")
        ),
    )
    with op.batch_alter_table("embeddings", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_embeddings_posting_id"), ["posting_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_embeddings_profile_id"), ["profile_id"], unique=False)

    op.create_table(
        "invitations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("posting_id", sa.String(length=36), nullable=False),
        sa.Column("profile_id", sa.String(length=36), nullable=False),
        sa.Column("recruiter_id", sa.String(length=36), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "sent",
                "accepted",
                "declined",
                name="invitation_status",
                native_enum=False,
                create_constraint=False,
                length=20,
            ),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('sent', 'accepted', 'declined')",
            name=op.f("ck_invitations_invitation_status"),
        ),
        sa.ForeignKeyConstraint(
            ["posting_id"],
            ["job_postings.id"],
            name=op.f("fk_invitations_posting_id_job_postings"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["profile_id"],
            ["developer_profiles.user_id"],
            name=op.f("fk_invitations_profile_id_developer_profiles"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["recruiter_id"],
            ["users.id"],
            name=op.f("fk_invitations_recruiter_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_invitations")),
        sa.UniqueConstraint("posting_id", "profile_id", name=op.f("uq_invitations_posting_id")),
    )
    with op.batch_alter_table("invitations", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_invitations_posting_id"), ["posting_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_invitations_profile_id"), ["profile_id"], unique=False)
        batch_op.create_index(
            batch_op.f("ix_invitations_recruiter_id"), ["recruiter_id"], unique=False
        )

    op.create_table(
        "match_scores",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("posting_id", sa.String(length=36), nullable=False),
        sa.Column("profile_id", sa.String(length=36), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("base_score", sa.Float(), nullable=False),
        sa.Column("components", sa.JSON(), nullable=False),
        sa.Column("llm_adjustment", sa.Integer(), nullable=False),
        sa.Column("reasons", sa.JSON(), nullable=False),
        sa.Column("feedback", sa.JSON(), nullable=False),
        sa.Column("profile_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("posting_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("model", sa.String(length=100), nullable=False),
        sa.Column("explained", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "llm_adjustment BETWEEN -10 AND 10", name=op.f("ck_match_scores_adjustment_range")
        ),
        sa.CheckConstraint("score BETWEEN 0 AND 100", name=op.f("ck_match_scores_score_range")),
        sa.ForeignKeyConstraint(
            ["posting_id"],
            ["job_postings.id"],
            name=op.f("fk_match_scores_posting_id_job_postings"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["profile_id"],
            ["developer_profiles.user_id"],
            name=op.f("fk_match_scores_profile_id_developer_profiles"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_match_scores")),
        sa.UniqueConstraint("posting_id", "profile_id", name=op.f("uq_match_scores_posting_id")),
    )
    with op.batch_alter_table("match_scores", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_match_scores_posting_id"), ["posting_id"], unique=False
        )
        batch_op.create_index(
            "ix_match_scores_posting_id_score", ["posting_id", "score"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_match_scores_profile_id"), ["profile_id"], unique=False
        )

    op.create_table(
        "skill_profiles",
        sa.Column("profile_id", sa.String(length=36), nullable=False),
        sa.Column("skills", sa.JSON(), nullable=False),
        sa.Column(
            "tier",
            sa.Enum(
                "junior", "mid", name="tier", native_enum=False, create_constraint=False, length=20
            ),
            nullable=False,
        ),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("tier IN ('junior', 'mid')", name=op.f("ck_skill_profiles_tier")),
        sa.ForeignKeyConstraint(
            ["profile_id"],
            ["developer_profiles.user_id"],
            name=op.f("fk_skill_profiles_profile_id_developer_profiles"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("profile_id", name=op.f("pk_skill_profiles")),
    )
    with op.batch_alter_table("applications", schema=None) as batch_op:
        batch_op.add_column(sa.Column("match_score_id", sa.String(length=36), nullable=True))
        batch_op.create_foreign_key(
            batch_op.f("fk_applications_match_score_id_match_scores"),
            "match_scores",
            ["match_score_id"],
            ["id"],
            ondelete="SET NULL",
        )

    with op.batch_alter_table("developer_profiles", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "open_to_opportunities", sa.Boolean(), server_default=sa.text("0"), nullable=False
            )
        )

    with op.batch_alter_table("job_postings", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("injection_flags", sa.JSON(), server_default="[]", nullable=False)
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("jobs", schema=None) as batch_op:
        batch_op.drop_constraint(batch_op.f("ck_jobs_job_kind"), type_="check")
        batch_op.create_check_constraint(
            batch_op.f("ck_jobs_job_kind"),
            "kind IN ('cv_parse', 'repo_analyze')",
        )

    with op.batch_alter_table("job_postings", schema=None) as batch_op:
        batch_op.drop_column("injection_flags")

    with op.batch_alter_table("developer_profiles", schema=None) as batch_op:
        batch_op.drop_column("open_to_opportunities")

    with op.batch_alter_table("applications", schema=None) as batch_op:
        batch_op.drop_constraint(
            batch_op.f("fk_applications_match_score_id_match_scores"), type_="foreignkey"
        )
        batch_op.drop_column("match_score_id")

    op.drop_table("skill_profiles")
    with op.batch_alter_table("match_scores", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_match_scores_profile_id"))
        batch_op.drop_index("ix_match_scores_posting_id_score")
        batch_op.drop_index(batch_op.f("ix_match_scores_posting_id"))

    op.drop_table("match_scores")
    with op.batch_alter_table("invitations", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_invitations_recruiter_id"))
        batch_op.drop_index(batch_op.f("ix_invitations_profile_id"))
        batch_op.drop_index(batch_op.f("ix_invitations_posting_id"))

    op.drop_table("invitations")
    with op.batch_alter_table("embeddings", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_embeddings_profile_id"))
        batch_op.drop_index(batch_op.f("ix_embeddings_posting_id"))

    op.drop_table("embeddings")
