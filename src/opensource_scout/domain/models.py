"""Core Pydantic domain models.

These are the in-memory, validated representations of everything the rest of
the application works with. SQLAlchemy rows (see
:mod:`opensource_scout.db.models`) are a separate, storage-shaped layer;
conversion between the two happens explicitly at the persistence boundary
rather than by sharing classes, so the domain layer stays free of ORM
concerns and easy to unit test.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator, model_validator

from opensource_scout.domain.enums import ApprovalKind, ReproductionStatus, ValidationStatus


class Profile(BaseModel):
    """The developer profile OpenSourceScout evaluates every project and
    issue against. See :mod:`opensource_scout.domain.profile` for the
    concrete instance used throughout the application."""

    model_config = ConfigDict(frozen=True)

    name: str
    github_username: str
    github_url: str
    operating_system: str
    hardware: str
    weekly_hours_min: float
    weekly_hours_max: float
    primary_objective: str
    skills: tuple[str, ...]
    interests: tuple[str, ...]
    hardware_constraints: tuple[str, ...]


class RepositoryCandidate(BaseModel):
    """A discovered repository, along with the metadata needed to score it."""

    owner: str
    name: str
    url: str
    description: str | None = None
    organization: str | None = None
    languages: tuple[str, ...] = ()
    topics: tuple[str, ...] = ()
    license_spdx: str | None = None
    stars: int = 0
    forks: int = 0
    archived: bool = False
    latest_commit_at: datetime | None = None
    latest_release_at: datetime | None = None
    open_issues: int = 0
    open_pull_requests: int = 0
    recent_merged_prs: int = 0
    recent_external_contributor_prs: int = 0
    has_contributing_guide: bool = False
    has_pr_template: bool = False
    has_issue_template: bool = False
    has_security_policy: bool = False
    discovered_via: tuple[str, ...] = Field(
        default=(), description="Search queries/domains that surfaced this repository."
    )

    @property
    def full_name(self) -> str:
        return f"{self.owner}/{self.name}"


class ScoreDimension(BaseModel):
    """One scored dimension with its bound and supporting evidence.

    ``value`` is always validated against ``[0, max_value]`` at construction
    time — this is what lets :mod:`opensource_scout.scoring` reject a
    malformed (out-of-range or evidence-free) LLM assessment before it can
    silently corrupt a ranking.
    """

    name: str
    value: int
    max_value: int
    evidence: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _in_range(self) -> ScoreDimension:
        if not (0 <= self.value <= self.max_value):
            raise ValueError(
                f"score {self.value} out of range [0, {self.max_value}] for dimension {self.name!r}"
            )
        return self


class ProjectScore(BaseModel):
    """Deterministic score for one repository candidate.

    Every dimension and the total are computed by plain Python in
    :mod:`opensource_scout.scoring.project` — never by an LLM — per the
    project's cost-and-trust rules.
    """

    repository_full_name: str
    career_relevance: ScoreDimension
    acceptance_probability: ScoreDimension
    technical_depth: ScoreDimension
    maintainer_activity: ScoreDimension
    hardware_compatibility: ScoreDimension
    repeat_contribution_value: ScoreDimension
    penalties: tuple[str, ...] = Field(
        default=(), description="Human-readable reasons points were deducted."
    )
    penalty_points: int = 0

    @property
    def total(self) -> int:
        raw = (
            self.career_relevance.value
            + self.acceptance_probability.value
            + self.technical_depth.value
            + self.maintainer_activity.value
            + self.hardware_compatibility.value
            + self.repeat_contribution_value.value
        )
        return max(0, raw - self.penalty_points)


class IssueCandidate(BaseModel):
    """A discovered issue, along with the metadata needed to score and
    reject/accept it as a contribution target."""

    repository_full_name: str
    number: int
    title: str
    url: str
    body: str = ""
    labels: tuple[str, ...] = ()
    assignees: tuple[str, ...] = ()
    linked_pull_requests: tuple[str, ...] = ()
    comment_count: int = 0
    created_at: datetime | None = None
    updated_at: datetime | None = None
    has_active_assignee: bool = False
    has_competing_pull_request: bool = False


class IssueScore(BaseModel):
    """Deterministic score for one issue candidate. See ``ProjectScore`` for
    the same evidence/validation guarantees."""

    issue_key: str
    career_relevance: ScoreDimension
    scope_clarity: ScoreDimension
    acceptance_probability: ScoreDimension
    technical_value: ScoreDimension
    testability: ScoreDimension
    schedule_fit: ScoreDimension
    rejection_reasons: tuple[str, ...] = ()

    @property
    def rejected(self) -> bool:
        return len(self.rejection_reasons) > 0

    @property
    def total(self) -> int:
        return (
            self.career_relevance.value
            + self.scope_clarity.value
            + self.acceptance_probability.value
            + self.technical_value.value
            + self.testability.value
            + self.schedule_fit.value
        )


class ContributionRule(BaseModel):
    """One extracted contribution rule for a repository, always traceable
    back to the file and excerpt it came from — per the requirement that
    every extracted rule carry its own evidence rather than being asserted
    from a summary."""

    repository_full_name: str
    category: str
    file_path: str
    heading_or_range: str
    confidence: float
    excerpt: str

    @field_validator("confidence")
    @classmethod
    def _confidence_in_range(cls, value: float) -> float:
        if not (0.0 <= value <= 1.0):
            raise ValueError(f"confidence {value} out of range [0, 1]")
        return value


class Approval(BaseModel):
    """A single-use, expiring human approval for one specific external
    action on one specific contribution. Required before the workflow state
    machine allows ``BRANCH_PUSHED`` or ``PR_OPENED`` for an external repo."""

    approval_id: str
    contribution_id: str
    kind: ApprovalKind
    granted_at: datetime
    expires_at: datetime
    used_at: datetime | None = None
    note: str | None = None

    def is_valid(self, *, at: datetime) -> bool:
        return self.used_at is None and self.granted_at <= at <= self.expires_at


class ReproductionReport(BaseModel):
    status: ReproductionStatus
    base_commit_sha: str
    summary: str
    evidence: tuple[str, ...] = ()
    likely_affected_files: tuple[str, ...] = ()


class ValidationResult(BaseModel):
    command: str
    status: ValidationStatus
    exit_code: int | None = None
    duration_seconds: float | None = None
    output_excerpt: str = ""
    same_failure_on_base_commit: bool | None = None


class ContributionRecord(BaseModel):
    """The persistent record of one attempted contribution, tracked from
    project selection through release and résumé generation."""

    contribution_id: str
    repository_full_name: str
    issue_number: int | None = None
    state: str
    base_commit_sha: str | None = None
    branch_name: str | None = None
    pull_request_url: str | None = None
    created_at: datetime
    updated_at: datetime
    skills_demonstrated: tuple[str, ...] = ()
    resume_bullet: str | None = None

    @field_validator("resume_bullet")
    @classmethod
    def _bullet_requires_merge(cls, value: str | None, info: ValidationInfo) -> str | None:
        if value and info.data.get("state") not in {"MERGED", "RELEASED"}:
            raise ValueError("resume_bullet may only be set once a contribution is MERGED")
        return value
