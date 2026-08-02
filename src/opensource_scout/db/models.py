"""SQLAlchemy 2 ORM models — the storage-shaped mirror of the domain layer.

These rows are intentionally simple and mostly-flat (JSON columns for
variable-shaped evidence/metadata) so that resuming a workflow after a
restart is just "replay ``workflow_transitions`` for a contribution and
rebuild in-memory state" rather than something requiring bespoke recovery
logic per table.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import JSON, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


class ProjectRow(Base):
    """A discovered and (optionally) scored repository candidate."""

    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True)
    full_name: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    url: Mapped[str] = mapped_column(String(512))
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    score_json: Mapped[dict | None] = mapped_column(JSON, default=None)
    score_total: Mapped[int | None] = mapped_column(default=None, index=True)
    selected: Mapped[bool] = mapped_column(default=False)
    discovered_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )


class IssueRow(Base):
    """A discovered and (optionally) scored issue candidate."""

    __tablename__ = "issues"
    __table_args__ = (
        Index("ix_issues_repo_number", "repository_full_name", "number", unique=True),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    repository_full_name: Mapped[str] = mapped_column(String(255), index=True)
    number: Mapped[int]
    title: Mapped[str] = mapped_column(String(1024))
    url: Mapped[str] = mapped_column(String(512))
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    score_json: Mapped[dict | None] = mapped_column(JSON, default=None)
    score_total: Mapped[int | None] = mapped_column(default=None)
    rejected: Mapped[bool] = mapped_column(default=False)
    selected: Mapped[bool] = mapped_column(default=False)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )


class ContributionRow(Base):
    """The persistent record of one attempted contribution."""

    __tablename__ = "contributions"

    id: Mapped[int] = mapped_column(primary_key=True)
    contribution_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    repository_full_name: Mapped[str] = mapped_column(String(255), index=True)
    issue_number: Mapped[int | None] = mapped_column(default=None)
    state: Mapped[str] = mapped_column(String(64), index=True)
    base_commit_sha: Mapped[str | None] = mapped_column(String(64), default=None)
    branch_name: Mapped[str | None] = mapped_column(String(255), default=None)
    pull_request_url: Mapped[str | None] = mapped_column(String(512), default=None)
    resume_bullet: Mapped[str | None] = mapped_column(Text, default=None)
    extra_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )


class WorkflowTransitionRow(Base):
    """One recorded workflow state transition. Replaying these in order for
    a given ``contribution_id`` reconstructs its current state after a
    process restart — this table is the resumability mechanism, not just an
    audit log."""

    __tablename__ = "workflow_transitions"
    __table_args__ = (Index("ix_transitions_contribution", "contribution_id", "id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    contribution_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("contributions.contribution_id"), index=True
    )
    from_state: Mapped[str] = mapped_column(String(64))
    to_state: Mapped[str] = mapped_column(String(64))
    evidence: Mapped[str] = mapped_column(Text, default="")
    occurred_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class ApprovalRow(Base):
    """A single-use, expiring human approval for one external action."""

    __tablename__ = "approvals"

    id: Mapped[int] = mapped_column(primary_key=True)
    approval_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    contribution_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("contributions.contribution_id"), index=True
    )
    kind: Mapped[str] = mapped_column(String(64))
    granted_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    note: Mapped[str | None] = mapped_column(Text, default=None)


class LlmCallRow(Base):
    """One recorded LLM call: model, usage, cost, and cache-relevant hashes.
    Never stores the raw token content of prompts/responses — only hashes —
    so this table can't itself become a place secrets or proprietary source
    leak to."""

    __tablename__ = "llm_calls"

    id: Mapped[int] = mapped_column(primary_key=True)
    task_category: Mapped[str] = mapped_column(String(64), index=True)
    model: Mapped[str] = mapped_column(String(128))
    prompt_hash: Mapped[str] = mapped_column(String(64), index=True)
    response_hash: Mapped[str | None] = mapped_column(String(64), default=None)
    input_tokens: Mapped[int] = mapped_column(default=0)
    output_tokens: Mapped[int] = mapped_column(default=0)
    estimated_cost_usd: Mapped[float] = mapped_column(default=0.0)
    latency_ms: Mapped[int | None] = mapped_column(default=None)
    cache_status: Mapped[str] = mapped_column(String(16), default="MISS")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class CommandRunRow(Base):
    """One recorded safe-command execution (see
    :mod:`opensource_scout.execution`). ``stdout``/``stderr`` are stored
    only after redaction."""

    __tablename__ = "command_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    contribution_id: Mapped[str | None] = mapped_column(String(64), default=None, index=True)
    command_json: Mapped[dict] = mapped_column(JSON)
    working_directory: Mapped[str] = mapped_column(String(1024))
    started_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    duration_seconds: Mapped[float | None] = mapped_column(default=None)
    exit_code: Mapped[int | None] = mapped_column(default=None)
    stdout_excerpt: Mapped[str] = mapped_column(Text, default="")
    stderr_excerpt: Mapped[str] = mapped_column(Text, default="")
    timed_out: Mapped[bool] = mapped_column(default=False)
    risk_classification: Mapped[str] = mapped_column(String(32), default="read_only")


class HttpCacheRow(Base):
    """Conditional-request cache for the GitHub client: ETag plus the last
    response body, keyed by request URL."""

    __tablename__ = "http_cache"

    id: Mapped[int] = mapped_column(primary_key=True)
    request_key: Mapped[str] = mapped_column(String(1024), unique=True, index=True)
    etag: Mapped[str | None] = mapped_column(String(255), default=None)
    last_modified: Mapped[str | None] = mapped_column(String(255), default=None)
    body_json: Mapped[dict | list | None] = mapped_column(JSON, default=None)
    status_code: Mapped[int] = mapped_column(default=200)
    fetched_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
