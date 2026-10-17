# Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform.
"""initial

Revision ID: 0001
Revises:
Create Date: 2026-10-17 14:52:32.926941

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("email", sa.String(length=254), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column(
            "role",
            sa.Enum(
                "developer",
                "recruiter",
                "admin",
                name="role",
                native_enum=False,
                create_constraint=False,
                length=20,
            ),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "role IN ('developer', 'recruiter', 'admin')", name=op.f("ck_users_role")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("email", name=op.f("uq_users_email")),
    )
    op.create_table(
        "connections",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("requester_id", sa.String(length=36), nullable=False),
        sa.Column("addressee_id", sa.String(length=36), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "accepted",
                "declined",
                name="connection_status",
                native_enum=False,
                create_constraint=False,
                length=20,
            ),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('pending', 'accepted', 'declined')",
            name=op.f("ck_connections_connection_status"),
        ),
        sa.CheckConstraint("requester_id != addressee_id", name=op.f("ck_connections_not_self")),
        sa.ForeignKeyConstraint(
            ["addressee_id"],
            ["users.id"],
            name=op.f("fk_connections_addressee_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["requester_id"],
            ["users.id"],
            name=op.f("fk_connections_requester_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_connections")),
        sa.UniqueConstraint(
            "requester_id", "addressee_id", name=op.f("uq_connections_requester_id")
        ),
    )
    with op.batch_alter_table("connections", schema=None) as batch_op:
        batch_op.create_index("ix_connections_addressee_id", ["addressee_id"], unique=False)

    op.create_table(
        "developer_profiles",
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("headline", sa.String(length=120), nullable=True),
        sa.Column("bio", sa.String(length=2000), nullable=True),
        sa.Column("location", sa.String(length=100), nullable=True),
        sa.Column(
            "experience_tier",
            sa.Enum(
                "junior", "mid", name="tier", native_enum=False, create_constraint=False, length=20
            ),
            nullable=True,
        ),
        sa.Column("github_username", sa.String(length=39), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "experience_tier IN ('junior', 'mid')", name=op.f("ck_developer_profiles_tier")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_developer_profiles_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id", name=op.f("pk_developer_profiles")),
    )
    op.create_table(
        "job_postings",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("recruiter_id", sa.String(length=36), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("required_skills", sa.JSON(), nullable=False),
        sa.Column("optional_skills", sa.JSON(), nullable=False),
        sa.Column(
            "tier",
            sa.Enum(
                "junior", "mid", name="tier", native_enum=False, create_constraint=False, length=20
            ),
            nullable=True,
        ),
        sa.Column("salary_min", sa.Integer(), nullable=True),
        sa.Column("salary_max", sa.Integer(), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=True),
        sa.Column("location", sa.String(length=100), nullable=True),
        sa.Column("remote", sa.Boolean(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "draft",
                "open",
                "closed",
                name="posting_status",
                native_enum=False,
                create_constraint=False,
                length=20,
            ),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('draft', 'open', 'closed')", name=op.f("ck_job_postings_posting_status")
        ),
        sa.CheckConstraint("tier IN ('junior', 'mid')", name=op.f("ck_job_postings_tier")),
        sa.CheckConstraint(
            "salary_max IS NULL OR salary_max >= 0", name=op.f("ck_job_postings_salary_max_nonneg")
        ),
        sa.CheckConstraint(
            "salary_min IS NULL OR salary_max IS NULL OR salary_min <= salary_max",
            name=op.f("ck_job_postings_salary_order"),
        ),
        sa.CheckConstraint(
            "salary_min IS NULL OR salary_min >= 0", name=op.f("ck_job_postings_salary_min_nonneg")
        ),
        sa.ForeignKeyConstraint(
            ["recruiter_id"],
            ["users.id"],
            name=op.f("fk_job_postings_recruiter_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_job_postings")),
    )
    with op.batch_alter_table("job_postings", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_job_postings_recruiter_id"), ["recruiter_id"], unique=False
        )

    op.create_table(
        "jobs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column(
            "kind",
            sa.Enum(
                "cv_parse",
                "repo_analyze",
                name="job_kind",
                native_enum=False,
                create_constraint=False,
                length=20,
            ),
            nullable=False,
        ),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "queued",
                "running",
                "done",
                "failed",
                name="job_status",
                native_enum=False,
                create_constraint=False,
                length=20,
            ),
            nullable=False,
        ),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("kind IN ('cv_parse', 'repo_analyze')", name=op.f("ck_jobs_job_kind")),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'done', 'failed')", name=op.f("ck_jobs_job_status")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_jobs_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_jobs")),
    )
    with op.batch_alter_table("jobs", schema=None) as batch_op:
        batch_op.create_index("ix_jobs_status_created_at", ["status", "created_at"], unique=False)
        batch_op.create_index(batch_op.f("ix_jobs_user_id"), ["user_id"], unique=False)

    op.create_table(
        "applications",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("job_posting_id", sa.String(length=36), nullable=False),
        sa.Column("profile_id", sa.String(length=36), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "submitted",
                "reviewing",
                "interview",
                "rejected",
                "accepted",
                "withdrawn",
                name="application_status",
                native_enum=False,
                create_constraint=False,
                length=20,
            ),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('submitted', 'reviewing', 'interview', 'rejected', 'accepted', 'withdrawn')",
            name=op.f("ck_applications_application_status"),
        ),
        sa.ForeignKeyConstraint(
            ["job_posting_id"],
            ["job_postings.id"],
            name=op.f("fk_applications_job_posting_id_job_postings"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["profile_id"],
            ["developer_profiles.user_id"],
            name=op.f("fk_applications_profile_id_developer_profiles"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_applications")),
        sa.UniqueConstraint(
            "job_posting_id", "profile_id", name=op.f("uq_applications_job_posting_id")
        ),
    )
    with op.batch_alter_table("applications", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_applications_job_posting_id"), ["job_posting_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_applications_profile_id"), ["profile_id"], unique=False
        )

    op.create_table(
        "cv_documents",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("profile_id", sa.String(length=36), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "parsed",
                "needs_text",
                "failed",
                name="cv_status",
                native_enum=False,
                create_constraint=False,
                length=20,
            ),
            nullable=False,
        ),
        sa.Column("extracted_text", sa.Text(), nullable=True),
        sa.Column("injection_flags", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('pending', 'parsed', 'needs_text', 'failed')",
            name=op.f("ck_cv_documents_cv_status"),
        ),
        sa.ForeignKeyConstraint(
            ["profile_id"],
            ["developer_profiles.user_id"],
            name=op.f("fk_cv_documents_profile_id_developer_profiles"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_cv_documents")),
    )
    with op.batch_alter_table("cv_documents", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_cv_documents_profile_id"), ["profile_id"], unique=False
        )

    op.create_table(
        "repositories",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("profile_id", sa.String(length=36), nullable=False),
        sa.Column("owner", sa.String(length=39), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("is_fork", sa.Boolean(), nullable=False),
        sa.Column("stars", sa.Integer(), nullable=False),
        sa.Column("pushed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["profile_id"],
            ["developer_profiles.user_id"],
            name=op.f("fk_repositories_profile_id_developer_profiles"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_repositories")),
        sa.UniqueConstraint("profile_id", "owner", "name", name=op.f("uq_repositories_profile_id")),
    )
    with op.batch_alter_table("repositories", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_repositories_profile_id"), ["profile_id"], unique=False
        )

    op.create_table(
        "skill_badges",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("profile_id", sa.String(length=36), nullable=False),
        sa.Column("skill", sa.String(length=100), nullable=False),
        sa.Column("level", sa.Integer(), nullable=False),
        sa.Column(
            "source",
            sa.Enum(
                "cv",
                "repo",
                "assessment",
                name="badge_source",
                native_enum=False,
                create_constraint=False,
                length=20,
            ),
            nullable=False,
        ),
        sa.Column("evidence", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "source IN ('cv', 'repo', 'assessment')", name=op.f("ck_skill_badges_badge_source")
        ),
        sa.ForeignKeyConstraint(
            ["profile_id"],
            ["developer_profiles.user_id"],
            name=op.f("fk_skill_badges_profile_id_developer_profiles"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_skill_badges")),
    )
    with op.batch_alter_table("skill_badges", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_skill_badges_profile_id"), ["profile_id"], unique=False
        )

    op.create_table(
        "application_status_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("application_id", sa.String(length=36), nullable=False),
        sa.Column(
            "from_status",
            sa.Enum(
                "submitted",
                "reviewing",
                "interview",
                "rejected",
                "accepted",
                "withdrawn",
                name="from_status",
                native_enum=False,
                create_constraint=False,
                length=20,
            ),
            nullable=True,
        ),
        sa.Column(
            "to_status",
            sa.Enum(
                "submitted",
                "reviewing",
                "interview",
                "rejected",
                "accepted",
                "withdrawn",
                name="to_status",
                native_enum=False,
                create_constraint=False,
                length=20,
            ),
            nullable=False,
        ),
        sa.Column("actor_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "from_status IN ('submitted', 'reviewing', 'interview', 'rejected', 'accepted', 'withdrawn')",
            name=op.f("ck_application_status_events_from_status"),
        ),
        sa.CheckConstraint(
            "to_status IN ('submitted', 'reviewing', 'interview', 'rejected', 'accepted', 'withdrawn')",
            name=op.f("ck_application_status_events_to_status"),
        ),
        sa.ForeignKeyConstraint(
            ["application_id"],
            ["applications.id"],
            name=op.f("fk_application_status_events_application_id_applications"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_application_status_events")),
    )
    with op.batch_alter_table("application_status_events", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_application_status_events_application_id"),
            ["application_id"],
            unique=False,
        )

    op.create_table(
        "cv_parses",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("cv_document_id", sa.String(length=36), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("model", sa.String(length=100), nullable=False),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["cv_document_id"],
            ["cv_documents.id"],
            name=op.f("fk_cv_parses_cv_document_id_cv_documents"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_cv_parses")),
    )
    with op.batch_alter_table("cv_parses", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_cv_parses_cv_document_id"), ["cv_document_id"], unique=False
        )

    op.create_table(
        "repo_analyses",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("repository_id", sa.String(length=36), nullable=False),
        sa.Column("commit_sha", sa.String(length=40), nullable=False),
        sa.Column("metrics", sa.JSON(), nullable=False),
        sa.Column("assessment", sa.JSON(), nullable=False),
        sa.Column("tutorial_likelihood", sa.Float(), nullable=False),
        sa.Column("model", sa.String(length=100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["repository_id"],
            ["repositories.id"],
            name=op.f("fk_repo_analyses_repository_id_repositories"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_repo_analyses")),
    )
    with op.batch_alter_table("repo_analyses", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_repo_analyses_repository_id"), ["repository_id"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("repo_analyses", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_repo_analyses_repository_id"))

    op.drop_table("repo_analyses")
    with op.batch_alter_table("cv_parses", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_cv_parses_cv_document_id"))

    op.drop_table("cv_parses")
    with op.batch_alter_table("application_status_events", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_application_status_events_application_id"))

    op.drop_table("application_status_events")
    with op.batch_alter_table("skill_badges", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_skill_badges_profile_id"))

    op.drop_table("skill_badges")
    with op.batch_alter_table("repositories", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_repositories_profile_id"))

    op.drop_table("repositories")
    with op.batch_alter_table("cv_documents", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_cv_documents_profile_id"))

    op.drop_table("cv_documents")
    with op.batch_alter_table("applications", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_applications_profile_id"))
        batch_op.drop_index(batch_op.f("ix_applications_job_posting_id"))

    op.drop_table("applications")
    with op.batch_alter_table("jobs", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_jobs_user_id"))
        batch_op.drop_index("ix_jobs_status_created_at")

    op.drop_table("jobs")
    with op.batch_alter_table("job_postings", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_job_postings_recruiter_id"))

    op.drop_table("job_postings")
    op.drop_table("developer_profiles")
    with op.batch_alter_table("connections", schema=None) as batch_op:
        batch_op.drop_index("ix_connections_addressee_id")

    op.drop_table("connections")
    op.drop_table("users")
