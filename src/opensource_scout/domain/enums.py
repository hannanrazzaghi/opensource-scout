"""Shared enumerations used across the domain layer."""

from __future__ import annotations

from enum import StrEnum


class WorkflowState(StrEnum):
    """States of a single contribution's lifecycle, from project discovery
    through a merged and released pull request.

    See :mod:`opensource_scout.workflows.state_machine` for the transition
    table and the approval requirements gating ``BRANCH_PUSHED`` and
    ``PR_OPENED`` for external repositories.
    """

    PROFILE_READY = "PROFILE_READY"
    PROJECT_DISCOVERY = "PROJECT_DISCOVERY"
    PROJECT_SELECTED = "PROJECT_SELECTED"
    REPOSITORY_INSPECTED = "REPOSITORY_INSPECTED"
    ISSUE_DISCOVERY = "ISSUE_DISCOVERY"
    ISSUE_SELECTED = "ISSUE_SELECTED"
    ISSUE_REPRODUCED = "ISSUE_REPRODUCED"
    IMPLEMENTATION_PLANNED = "IMPLEMENTATION_PLANNED"
    IMPLEMENTING = "IMPLEMENTING"
    VALIDATING = "VALIDATING"
    PR_PREPARED = "PR_PREPARED"
    AWAITING_PUSH_APPROVAL = "AWAITING_PUSH_APPROVAL"
    BRANCH_PUSHED = "BRANCH_PUSHED"
    AWAITING_PR_APPROVAL = "AWAITING_PR_APPROVAL"
    PR_OPENED = "PR_OPENED"
    REVIEW_IN_PROGRESS = "REVIEW_IN_PROGRESS"
    MERGED = "MERGED"
    RELEASED = "RELEASED"
    ABANDONED = "ABANDONED"
    BLOCKED = "BLOCKED"


class ApprovalKind(StrEnum):
    """The specific external action an :class:`~opensource_scout.domain.models.Approval`
    authorizes. Each is single-use and tied to one contribution."""

    PUSH_EXTERNAL_BRANCH = "PUSH_EXTERNAL_BRANCH"
    OPEN_EXTERNAL_PULL_REQUEST = "OPEN_EXTERNAL_PULL_REQUEST"


class ReproductionStatus(StrEnum):
    CONFIRMED = "CONFIRMED"
    PARTIALLY_CONFIRMED = "PARTIALLY_CONFIRMED"
    NOT_REPRODUCED = "NOT_REPRODUCED"
    ALREADY_FIXED = "ALREADY_FIXED"
    ENVIRONMENT_BLOCKED = "ENVIRONMENT_BLOCKED"
    NEEDS_CLARIFICATION = "NEEDS_CLARIFICATION"
    POTENTIAL_SECURITY_ISSUE = "POTENTIAL_SECURITY_ISSUE"


class ValidationStatus(StrEnum):
    PASSED = "PASSED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"
    UNAVAILABLE = "UNAVAILABLE"
    TIMED_OUT = "TIMED_OUT"
