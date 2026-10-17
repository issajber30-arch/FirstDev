# Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform.
import enum
import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import TypeDecorator


class Base(DeclarativeBase):
    # Stable constraint names keep Alembic autogenerate and batch mode deterministic.
    metadata = MetaData(
        naming_convention={
            "ix": "ix_%(column_0_label)s",
            "uq": "uq_%(table_name)s_%(column_0_name)s",
            "ck": "ck_%(table_name)s_%(constraint_name)s",
            "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
            "pk": "pk_%(table_name)s",
        }
    )


class Role(enum.StrEnum):
    developer = "developer"
    recruiter = "recruiter"
    admin = "admin"


class Tier(enum.StrEnum):
    junior = "junior"
    mid = "mid"


class ConnectionStatus(enum.StrEnum):
    pending = "pending"
    accepted = "accepted"
    declined = "declined"


class BadgeSource(enum.StrEnum):
    cv = "cv"
    repo = "repo"
    assessment = "assessment"


class CvStatus(enum.StrEnum):
    pending = "pending"
    parsed = "parsed"
    needs_text = "needs_text"
    failed = "failed"


class PostingStatus(enum.StrEnum):
    draft = "draft"
    open = "open"
    closed = "closed"


class ApplicationStatus(enum.StrEnum):
    submitted = "submitted"
    reviewing = "reviewing"
    interview = "interview"
    rejected = "rejected"
    accepted = "accepted"
    withdrawn = "withdrawn"


class JobKind(enum.StrEnum):
    cv_parse = "cv_parse"
    repo_analyze = "repo_analyze"


class JobStatus(enum.StrEnum):
    queued = "queued"
    running = "running"
    done = "done"
    failed = "failed"


def _enum(e: type[enum.StrEnum], name: str) -> Enum:
    # Non-native enum + CHECK so SQLite and Postgres enforce the same values.
    return Enum(e, name=name, native_enum=False, create_constraint=True, length=20)


class UTCDateTime(TypeDecorator[datetime]):
    """Always-aware UTC datetimes. SQLite drops tzinfo on read, which breaks comparisons."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("naive datetime; use datetime.now(UTC)")
        return value.astimezone(UTC) if value is not None else None

    def process_result_value(self, value: datetime | None, dialect) -> datetime | None:
        if value is not None and value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(UTC)


def _pk() -> Mapped[str]:
    return mapped_column(String(36), primary_key=True, default=_uuid)


def _fk(target: str) -> Mapped[str]:
    return mapped_column(String(36), ForeignKey(target, ondelete="CASCADE"), index=True)


def _created() -> Mapped[datetime]:
    return mapped_column(UTCDateTime(), default=_now)


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = _pk()
    email: Mapped[str] = mapped_column(String(254), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[Role] = mapped_column(_enum(Role, "role"))
    created_at: Mapped[datetime] = _created()


class DeveloperProfile(Base):
    __tablename__ = "developer_profiles"

    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    headline: Mapped[str | None] = mapped_column(String(120))
    bio: Mapped[str | None] = mapped_column(String(2000))
    location: Mapped[str | None] = mapped_column(String(100))
    experience_tier: Mapped[Tier | None] = mapped_column(_enum(Tier, "tier"))
    github_username: Mapped[str | None] = mapped_column(String(39))
    created_at: Mapped[datetime] = _created()


class Connection(Base):
    __tablename__ = "connections"
    __table_args__ = (
        UniqueConstraint("requester_id", "addressee_id"),
        CheckConstraint("requester_id != addressee_id", name="not_self"),
        Index("ix_connections_addressee_id", "addressee_id"),
    )

    id: Mapped[str] = _pk()
    requester_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE")
    )
    addressee_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE")
    )
    status: Mapped[ConnectionStatus] = mapped_column(
        _enum(ConnectionStatus, "connection_status"), default=ConnectionStatus.pending
    )
    created_at: Mapped[datetime] = _created()


class SkillBadge(Base):
    __tablename__ = "skill_badges"

    id: Mapped[str] = _pk()
    profile_id: Mapped[str] = _fk("developer_profiles.user_id")
    skill: Mapped[str] = mapped_column(String(100))
    level: Mapped[int] = mapped_column(Integer)
    source: Mapped[BadgeSource] = mapped_column(_enum(BadgeSource, "badge_source"))
    evidence: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = _created()


class CvDocument(Base):
    __tablename__ = "cv_documents"

    id: Mapped[str] = _pk()
    profile_id: Mapped[str] = _fk("developer_profiles.user_id")
    sha256: Mapped[str] = mapped_column(String(64))
    size: Mapped[int] = mapped_column(Integer)
    page_count: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[CvStatus] = mapped_column(_enum(CvStatus, "cv_status"), default=CvStatus.pending)
    extracted_text: Mapped[str | None] = mapped_column(Text)
    injection_flags: Mapped[list | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = _created()


class CvParse(Base):
    __tablename__ = "cv_parses"

    id: Mapped[str] = _pk()
    cv_document_id: Mapped[str] = _fk("cv_documents.id")
    schema_version: Mapped[int] = mapped_column(Integer)
    model: Mapped[str] = mapped_column(String(100))
    data: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = _created()


class Repository(Base):
    __tablename__ = "repositories"
    __table_args__ = (UniqueConstraint("profile_id", "owner", "name"),)

    id: Mapped[str] = _pk()
    profile_id: Mapped[str] = _fk("developer_profiles.user_id")
    owner: Mapped[str] = mapped_column(String(39))
    name: Mapped[str] = mapped_column(String(100))
    is_fork: Mapped[bool] = mapped_column(Boolean, default=False)
    stars: Mapped[int] = mapped_column(Integer, default=0)
    pushed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    created_at: Mapped[datetime] = _created()


class RepoAnalysis(Base):
    __tablename__ = "repo_analyses"

    id: Mapped[str] = _pk()
    repository_id: Mapped[str] = _fk("repositories.id")
    commit_sha: Mapped[str] = mapped_column(String(40))
    metrics: Mapped[dict] = mapped_column(JSON)
    assessment: Mapped[dict] = mapped_column(JSON)
    tutorial_likelihood: Mapped[float] = mapped_column(Float)
    model: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = _created()


class JobPosting(Base):
    __tablename__ = "job_postings"
    __table_args__ = (
        CheckConstraint("salary_min IS NULL OR salary_min >= 0", name="salary_min_nonneg"),
        CheckConstraint("salary_max IS NULL OR salary_max >= 0", name="salary_max_nonneg"),
        CheckConstraint(
            "salary_min IS NULL OR salary_max IS NULL OR salary_min <= salary_max",
            name="salary_order",
        ),
    )

    id: Mapped[str] = _pk()
    recruiter_id: Mapped[str] = _fk("users.id")
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text)
    required_skills: Mapped[list] = mapped_column(JSON, default=list)
    optional_skills: Mapped[list] = mapped_column(JSON, default=list)
    tier: Mapped[Tier | None] = mapped_column(_enum(Tier, "tier"))
    salary_min: Mapped[int | None] = mapped_column(Integer)
    salary_max: Mapped[int | None] = mapped_column(Integer)
    currency: Mapped[str | None] = mapped_column(String(3))
    location: Mapped[str | None] = mapped_column(String(100))
    remote: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[PostingStatus] = mapped_column(
        _enum(PostingStatus, "posting_status"), default=PostingStatus.draft
    )
    created_at: Mapped[datetime] = _created()


class Application(Base):
    __tablename__ = "applications"
    __table_args__ = (UniqueConstraint("job_posting_id", "profile_id"),)

    id: Mapped[str] = _pk()
    job_posting_id: Mapped[str] = _fk("job_postings.id")
    profile_id: Mapped[str] = _fk("developer_profiles.user_id")
    status: Mapped[ApplicationStatus] = mapped_column(
        _enum(ApplicationStatus, "application_status"), default=ApplicationStatus.submitted
    )
    created_at: Mapped[datetime] = _created()


class ApplicationStatusEvent(Base):
    __tablename__ = "application_status_events"

    id: Mapped[str] = _pk()
    application_id: Mapped[str] = _fk("applications.id")
    from_status: Mapped[ApplicationStatus | None] = mapped_column(
        _enum(ApplicationStatus, "from_status")
    )
    to_status: Mapped[ApplicationStatus] = mapped_column(_enum(ApplicationStatus, "to_status"))
    actor_id: Mapped[str | None] = mapped_column(String(36))  # no FK: keep history if actor leaves
    created_at: Mapped[datetime] = _created()


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (Index("ix_jobs_status_created_at", "status", "created_at"),)

    id: Mapped[str] = _pk()
    # Owner is needed so GET /jobs/{id} can be ownership-checked and DELETE /me removes the row.
    user_id: Mapped[str] = _fk("users.id")
    kind: Mapped[JobKind] = mapped_column(_enum(JobKind, "job_kind"))
    payload: Mapped[dict] = mapped_column(JSON)
    status: Mapped[JobStatus] = mapped_column(
        _enum(JobStatus, "job_status"), default=JobStatus.queued
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)
    locked_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    run_after: Mapped[datetime | None] = mapped_column(UTCDateTime())  # retry backoff
    created_at: Mapped[datetime] = _created()
