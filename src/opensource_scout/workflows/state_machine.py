"""The contribution workflow state machine.

A contribution moves through a fixed sequence of :class:`WorkflowState`
values. The transition table below is the single source of truth for which
moves are legal; every transition is recorded with a timestamp and evidence
so the workflow is fully resumable after a restart (see
:mod:`opensource_scout.db.models.WorkflowTransitionRow`).

Two states are specially gated: ``BRANCH_PUSHED`` and ``PR_OPENED`` are the
points at which OpenSourceScout would act on an *external* repository, and
per the project's authorization rules they must never be reached without a
valid, unexpired, single-use :class:`~opensource_scout.domain.models.Approval`
of the matching kind. This module enforces that at the domain layer,
independent of whatever calls it.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime

from opensource_scout.domain.enums import ApprovalKind, WorkflowState
from opensource_scout.domain.models import Approval

TERMINAL_STATES: frozenset[WorkflowState] = frozenset(
    {WorkflowState.RELEASED, WorkflowState.ABANDONED}
)

# States from which abandoning or blocking the contribution is always legal.
_ACTIVE_STATES: frozenset[WorkflowState] = frozenset(WorkflowState) - TERMINAL_STATES

_LINEAR_FLOW: Mapping[WorkflowState, frozenset[WorkflowState]] = {
    WorkflowState.PROFILE_READY: frozenset({WorkflowState.PROJECT_DISCOVERY}),
    WorkflowState.PROJECT_DISCOVERY: frozenset({WorkflowState.PROJECT_SELECTED}),
    WorkflowState.PROJECT_SELECTED: frozenset({WorkflowState.REPOSITORY_INSPECTED}),
    WorkflowState.REPOSITORY_INSPECTED: frozenset({WorkflowState.ISSUE_DISCOVERY}),
    WorkflowState.ISSUE_DISCOVERY: frozenset({WorkflowState.ISSUE_SELECTED}),
    WorkflowState.ISSUE_SELECTED: frozenset({WorkflowState.ISSUE_REPRODUCED}),
    WorkflowState.ISSUE_REPRODUCED: frozenset({WorkflowState.IMPLEMENTATION_PLANNED}),
    WorkflowState.IMPLEMENTATION_PLANNED: frozenset({WorkflowState.IMPLEMENTING}),
    WorkflowState.IMPLEMENTING: frozenset({WorkflowState.VALIDATING}),
    # Failed validation sends work back to IMPLEMENTING rather than forward.
    WorkflowState.VALIDATING: frozenset({WorkflowState.PR_PREPARED, WorkflowState.IMPLEMENTING}),
    WorkflowState.PR_PREPARED: frozenset({WorkflowState.AWAITING_PUSH_APPROVAL}),
    WorkflowState.AWAITING_PUSH_APPROVAL: frozenset({WorkflowState.BRANCH_PUSHED}),
    WorkflowState.BRANCH_PUSHED: frozenset({WorkflowState.AWAITING_PR_APPROVAL}),
    WorkflowState.AWAITING_PR_APPROVAL: frozenset({WorkflowState.PR_OPENED}),
    WorkflowState.PR_OPENED: frozenset({WorkflowState.REVIEW_IN_PROGRESS}),
    # Review feedback may require another implementation pass.
    WorkflowState.REVIEW_IN_PROGRESS: frozenset({WorkflowState.MERGED, WorkflowState.IMPLEMENTING}),
    WorkflowState.MERGED: frozenset({WorkflowState.RELEASED}),
    WorkflowState.RELEASED: frozenset(),
    WorkflowState.ABANDONED: frozenset(),
    # Resuming from BLOCKED can land back in any active state.
    WorkflowState.BLOCKED: _ACTIVE_STATES - {WorkflowState.BLOCKED},
}

# Every active state may also move to ABANDONED or BLOCKED.
TRANSITIONS: Mapping[WorkflowState, frozenset[WorkflowState]] = {
    state: (
        targets | frozenset({WorkflowState.ABANDONED, WorkflowState.BLOCKED})
        if state in _ACTIVE_STATES and state != WorkflowState.BLOCKED
        else targets
    )
    for state, targets in _LINEAR_FLOW.items()
}

# States that represent OpenSourceScout acting on an external repository and
# therefore require a matching, valid approval before the transition is
# permitted.
_APPROVAL_REQUIRED: Mapping[WorkflowState, ApprovalKind] = {
    WorkflowState.BRANCH_PUSHED: ApprovalKind.PUSH_EXTERNAL_BRANCH,
    WorkflowState.PR_OPENED: ApprovalKind.OPEN_EXTERNAL_PULL_REQUEST,
}


class InvalidTransitionError(Exception):
    """Raised when a transition is not permitted from the current state."""


class ApprovalRequiredError(Exception):
    """Raised when a gated transition is attempted without a valid, matching
    single-use approval."""


@dataclass(frozen=True)
class TransitionRecord:
    """A recorded, resumable workflow transition."""

    contribution_id: str
    from_state: WorkflowState
    to_state: WorkflowState
    at: datetime
    evidence: str


def is_external_action(state: WorkflowState) -> bool:
    return state in _APPROVAL_REQUIRED


def validate_transition(
    current: WorkflowState,
    target: WorkflowState,
    *,
    approval: Approval | None = None,
    now: datetime | None = None,
) -> None:
    """Raise if ``current -> target`` is not a legal transition.

    Does not mutate anything — callers persist the transition themselves
    (see :meth:`opensource_scout.db.repository...`) once validation passes,
    so the same check can be reused both when applying a real transition and
    when a caller wants to ask "is this allowed?" without committing to it.
    """
    allowed = TRANSITIONS.get(current, frozenset())
    if target not in allowed:
        raise InvalidTransitionError(
            f"cannot transition from {current} to {target} "
            f"(allowed: {sorted(s.value for s in allowed)})"
        )

    required_kind = _APPROVAL_REQUIRED.get(target)
    if required_kind is not None:
        if approval is None or approval.kind is not required_kind:
            raise ApprovalRequiredError(
                f"transition to {target} requires a granted {required_kind.value} approval"
            )
        check_time = now or approval.granted_at
        if not approval.is_valid(at=check_time):
            raise ApprovalRequiredError(
                f"approval {approval.approval_id} is expired or already used"
            )


def transition(
    contribution_id: str,
    current: WorkflowState,
    target: WorkflowState,
    *,
    evidence: str,
    approval: Approval | None = None,
    now: datetime | None = None,
) -> TransitionRecord:
    """Validate and produce a :class:`TransitionRecord` for ``current -> target``.

    Raises :class:`InvalidTransitionError` or :class:`ApprovalRequiredError`
    on rejection; callers should treat either as fatal for the requested
    transition and not partially apply it.
    """
    at = now or datetime.now()
    validate_transition(current, target, approval=approval, now=at)
    return TransitionRecord(
        contribution_id=contribution_id,
        from_state=current,
        to_state=target,
        at=at,
        evidence=evidence,
    )
