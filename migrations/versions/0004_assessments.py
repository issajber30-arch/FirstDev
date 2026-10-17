# Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform.
"""assessments

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-17 16:30:16.453934

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: str | Sequence[str] | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # Autogenerate does not see CHECK changes: widen jobs.kind for the new job kinds.
    with op.batch_alter_table("jobs", schema=None) as batch_op:
        batch_op.drop_constraint(batch_op.f("ck_jobs_job_kind"), type_="check")
        batch_op.create_check_constraint(
            batch_op.f("ck_jobs_job_kind"),
            "kind IN ('cv_parse', 'repo_analyze', 'embed_profile', 'embed_posting', 'score_pair', 'rank_posting', 'assessment_generate', 'assessment_grade')",
        )

    op.create_table(
        "assessments",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("profile_id", sa.String(length=36), nullable=False),
        sa.Column("posting_id", sa.String(length=36), nullable=True),
        sa.Column("application_id", sa.String(length=36), nullable=True),
        sa.Column(
            "kind",
            sa.Enum(
                "recruiter",
                "auto",
                "practice",
                name="assessment_kind",
                native_enum=False,
                create_constraint=False,
                length=20,
            ),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "generating",
                "ready",
                "in_progress",
                "submitted",
                "graded",
                "failed",
                "expired",
                name="assessment_status",
                native_enum=False,
                create_constraint=False,
                length=20,
            ),
            nullable=False,
        ),
        sa.Column("skills", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.String(length=36), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deadline", sa.DateTime(timezone=True), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("graded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("overall_pct", sa.Float(), nullable=True),
        sa.Column("skill_pcts", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "kind = 'practice' OR posting_id IS NOT NULL",
            name=op.f("ck_assessments_posting_for_non_practice"),
        ),
        sa.CheckConstraint(
            "kind IN ('recruiter', 'auto', 'practice')", name=op.f("ck_assessments_assessment_kind")
        ),
        sa.CheckConstraint(
            "status IN ('generating', 'ready', 'in_progress', 'submitted', 'graded', 'failed', 'expired')",
            name=op.f("ck_assessments_assessment_status"),
        ),
        sa.ForeignKeyConstraint(
            ["application_id"],
            ["applications.id"],
            name=op.f("fk_assessments_application_id_applications"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_assessments_created_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["posting_id"],
            ["job_postings.id"],
            name=op.f("fk_assessments_posting_id_job_postings"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["profile_id"],
            ["developer_profiles.user_id"],
            name=op.f("fk_assessments_profile_id_developer_profiles"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_assessments")),
        sa.UniqueConstraint("application_id", name=op.f("uq_assessments_application_id")),
    )
    with op.batch_alter_table("assessments", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_assessments_posting_id"), ["posting_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_assessments_profile_id"), ["profile_id"], unique=False)

    op.create_table(
        "assessment_questions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("assessment_id", sa.String(length=36), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column(
            "kind",
            sa.Enum(
                "mcq",
                "short",
                name="question_kind",
                native_enum=False,
                create_constraint=False,
                length=20,
            ),
            nullable=False,
        ),
        sa.Column("skill", sa.String(length=100), nullable=False),
        sa.Column("difficulty", sa.Integer(), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("options", sa.JSON(), nullable=True),
        sa.Column("correct_index", sa.Integer(), nullable=True),
        sa.Column("explanation", sa.Text(), nullable=True),
        sa.Column("rubric", sa.JSON(), nullable=True),
        sa.Column("model_answer", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "kind != 'mcq' OR (options IS NOT NULL AND correct_index BETWEEN 0 AND 3)",
            name=op.f("ck_assessment_questions_mcq_fields"),
        ),
        sa.CheckConstraint(
            "kind IN ('mcq', 'short')", name=op.f("ck_assessment_questions_question_kind")
        ),
        sa.ForeignKeyConstraint(
            ["assessment_id"],
            ["assessments.id"],
            name=op.f("fk_assessment_questions_assessment_id_assessments"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_assessment_questions")),
        sa.UniqueConstraint(
            "assessment_id", "position", name=op.f("uq_assessment_questions_assessment_id")
        ),
    )
    with op.batch_alter_table("assessment_questions", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_assessment_questions_assessment_id"), ["assessment_id"], unique=False
        )

    op.create_table(
        "assessment_answers",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("question_id", sa.String(length=36), nullable=False),
        sa.Column("choice_index", sa.Integer(), nullable=True),
        sa.Column("text", sa.Text(), nullable=True),
        sa.Column("points", sa.Float(), nullable=True),
        sa.Column("criteria_met", sa.JSON(), nullable=True),
        sa.Column("feedback", sa.Text(), nullable=True),
        sa.Column("injection_flags", sa.JSON(), nullable=False),
        sa.Column("answered_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["question_id"],
            ["assessment_questions.id"],
            name=op.f("fk_assessment_answers_question_id_assessment_questions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_assessment_answers")),
        sa.UniqueConstraint("question_id", name=op.f("uq_assessment_answers_question_id")),
    )
    with op.batch_alter_table("job_postings", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("auto_assessment", sa.Boolean(), server_default=sa.false(), nullable=False)
        )

    with op.batch_alter_table("skill_badges", schema=None) as batch_op:
        batch_op.add_column(sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    # Jobs of the new kinds would violate the narrowed CHECK.
    op.execute("DELETE FROM jobs WHERE kind IN ('assessment_generate', 'assessment_grade')")
    # Autogenerate does not see CHECK changes: widen jobs.kind for the new job kinds.
    with op.batch_alter_table("jobs", schema=None) as batch_op:
        batch_op.drop_constraint(batch_op.f("ck_jobs_job_kind"), type_="check")
        batch_op.create_check_constraint(
            batch_op.f("ck_jobs_job_kind"),
            "kind IN ('cv_parse', 'repo_analyze', 'embed_profile', 'embed_posting', 'score_pair', 'rank_posting')",
        )

    with op.batch_alter_table("skill_badges", schema=None) as batch_op:
        batch_op.drop_column("expires_at")

    with op.batch_alter_table("job_postings", schema=None) as batch_op:
        batch_op.drop_column("auto_assessment")

    op.drop_table("assessment_answers")
    with op.batch_alter_table("assessment_questions", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_assessment_questions_assessment_id"))

    op.drop_table("assessment_questions")
    with op.batch_alter_table("assessments", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_assessments_profile_id"))
        batch_op.drop_index(batch_op.f("ix_assessments_posting_id"))

    op.drop_table("assessments")
