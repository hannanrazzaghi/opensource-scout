from datetime import UTC, datetime, timedelta

import pytest

from opensource_scout.domain.enums import ApprovalKind, WorkflowState
from opensource_scout.domain.models import Approval
from opensource_scout.workflows.state_machine import (
    ApprovalRequiredError,
    InvalidTransitionError,
    transition,
    validate_transition,
)


def _approval(
    kind: ApprovalKind = ApprovalKind.PUSH_EXTERNAL_BRANCH,
    *,
    granted_at: datetime | None = None,
    expires_in: timedelta = timedelta(hours=1),
    used_at: datetime | None = None,
) -> Approval:
    granted = granted_at or datetime.now(UTC)
    return Approval(
        approval_id="a1",
        contribution_id="c1",
        kind=kind,
        granted_at=granted,
        expires_at=granted + expires_in,
        used_at=used_at,
    )


def test_valid_linear_transition_succeeds() -> None:
    record = transition(
        "c1", WorkflowState.PROFILE_READY, WorkflowState.PROJECT_DISCOVERY, evidence="started"
    )
    assert record.to_state is WorkflowState.PROJECT_DISCOVERY
    assert record.from_state is WorkflowState.PROFILE_READY


def test_invalid_transition_is_rejected() -> None:
    with pytest.raises(InvalidTransitionError):
        transition("c1", WorkflowState.PROFILE_READY, WorkflowState.MERGED, evidence="skip ahead")


def test_any_active_state_can_be_abandoned() -> None:
    record = transition(
        "c1", WorkflowState.ISSUE_REPRODUCED, WorkflowState.ABANDONED, evidence="lost interest"
    )
    assert record.to_state is WorkflowState.ABANDONED


def test_terminal_states_have_no_outgoing_transitions() -> None:
    with pytest.raises(InvalidTransitionError):
        transition("c1", WorkflowState.ABANDONED, WorkflowState.PROJECT_DISCOVERY, evidence="x")
    with pytest.raises(InvalidTransitionError):
        transition("c1", WorkflowState.RELEASED, WorkflowState.MERGED, evidence="x")


@pytest.mark.parametrize("target", [WorkflowState.BRANCH_PUSHED, WorkflowState.PR_OPENED])
def test_external_action_states_require_approval(target: WorkflowState) -> None:
    source = {
        WorkflowState.BRANCH_PUSHED: WorkflowState.AWAITING_PUSH_APPROVAL,
        WorkflowState.PR_OPENED: WorkflowState.AWAITING_PR_APPROVAL,
    }[target]
    with pytest.raises(ApprovalRequiredError):
        transition("c1", source, target, evidence="push", approval=None)


def test_wrong_approval_kind_is_rejected() -> None:
    approval = _approval(kind=ApprovalKind.OPEN_EXTERNAL_PULL_REQUEST)
    with pytest.raises(ApprovalRequiredError):
        transition(
            "c1",
            WorkflowState.AWAITING_PUSH_APPROVAL,
            WorkflowState.BRANCH_PUSHED,
            evidence="push",
            approval=approval,
        )


def test_valid_approval_permits_gated_transition() -> None:
    now = datetime.now(UTC)
    approval = _approval(granted_at=now)
    record = transition(
        "c1",
        WorkflowState.AWAITING_PUSH_APPROVAL,
        WorkflowState.BRANCH_PUSHED,
        evidence="push",
        approval=approval,
        now=now,
    )
    assert record.to_state is WorkflowState.BRANCH_PUSHED


def test_expired_approval_is_rejected() -> None:
    now = datetime.now(UTC)
    approval = _approval(granted_at=now - timedelta(hours=2), expires_in=timedelta(hours=1))
    with pytest.raises(ApprovalRequiredError):
        transition(
            "c1",
            WorkflowState.AWAITING_PUSH_APPROVAL,
            WorkflowState.BRANCH_PUSHED,
            evidence="push",
            approval=approval,
            now=now,
        )


def test_already_used_approval_is_rejected() -> None:
    now = datetime.now(UTC)
    approval = _approval(granted_at=now, used_at=now)
    with pytest.raises(ApprovalRequiredError):
        transition(
            "c1",
            WorkflowState.AWAITING_PUSH_APPROVAL,
            WorkflowState.BRANCH_PUSHED,
            evidence="push",
            approval=approval,
            now=now,
        )


def test_validate_transition_does_not_raise_for_legal_move() -> None:
    validate_transition(WorkflowState.MERGED, WorkflowState.RELEASED)


def test_blocked_can_resume_to_any_active_state() -> None:
    record = transition(
        "c1", WorkflowState.BLOCKED, WorkflowState.ISSUE_SELECTED, evidence="unblocked"
    )
    assert record.to_state is WorkflowState.ISSUE_SELECTED
