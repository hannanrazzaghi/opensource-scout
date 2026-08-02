"""Structured LLM response models.

Every LLM call that matters routes its output through one of these Pydantic
models. Field bounds mirror the corresponding deterministic score's range
(see :mod:`opensource_scout.scoring`) so an LLM assessment can never smuggle
an out-of-range value into a score that's supposed to be trustworthy by
construction. Evidence and explanation fields are required non-empty —
an assessment with no supporting evidence is rejected, not accepted with a
shrug.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, ValidationInfo, field_validator


def _non_empty(value: list[str]) -> list[str]:
    if not value or not any(v.strip() for v in value):
        raise ValueError("at least one non-empty entry is required")
    return value


class ProjectAssessment(BaseModel):
    """Subjective, evidence-backed input into
    :class:`~opensource_scout.domain.models.ProjectScore`'s
    ``career_relevance``/``technical_depth`` dimensions. Never used
    standalone — always range-validated and combined with deterministic
    signals by :mod:`opensource_scout.scoring.project`."""

    career_relevance: int = Field(ge=0, le=30)
    technical_depth: int = Field(ge=0, le=15)
    evidence: list[str]
    risks: list[str] = Field(default_factory=list)
    explanation: str = Field(min_length=1)

    @field_validator("evidence")
    @classmethod
    def _evidence_required(cls, value: list[str]) -> list[str]:
        return _non_empty(value)


class IssueAssessment(BaseModel):
    """Subjective, evidence-backed input into
    :class:`~opensource_scout.domain.models.IssueScore`'s
    ``scope_clarity``/``technical_value`` dimensions, plus effort estimation
    used by the implementation-planning workflow."""

    scope_clarity: int = Field(ge=0, le=20)
    technical_value: int = Field(ge=0, le=15)
    estimated_hours_min: float = Field(ge=0)
    estimated_hours_max: float = Field(ge=0)
    likely_files: list[str] = Field(default_factory=list)
    required_tests: list[str] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)
    explanation: str = Field(min_length=1)

    @field_validator("estimated_hours_max")
    @classmethod
    def _max_not_below_min(cls, value: float, info: ValidationInfo) -> float:
        min_hours = info.data.get("estimated_hours_min")
        if min_hours is not None and value < min_hours:
            raise ValueError("estimated_hours_max must be >= estimated_hours_min")
        return value


class ImplementationPlan(BaseModel):
    """A proposed fix, before any code is written. Required reading before
    :mod:`opensource_scout.workflows` allows a transition into
    ``IMPLEMENTING``."""

    problem: str = Field(min_length=1)
    root_cause_hypothesis: str = Field(min_length=1)
    proposed_changes: list[str]
    tests: list[str]
    alternatives: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    estimated_hours: float = Field(ge=0)

    @field_validator("proposed_changes", "tests")
    @classmethod
    def _required_non_empty(cls, value: list[str]) -> list[str]:
        return _non_empty(value)
