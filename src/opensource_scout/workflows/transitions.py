"""Shared helper for validating and persisting one workflow transition.

Pulled out of :mod:`opensource_scout.reports.contribution_report` so
:mod:`opensource_scout.reports.pr_report` (and anything else that advances a
contribution's state) records transitions the same way, through the same
validation.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from opensource_scout.db.models import WorkflowTransitionRow
from opensource_scout.domain.enums import WorkflowState
from opensource_scout.domain.models import Approval
from opensource_scout.workflows.state_machine import transition


def record_transition(
    session: Session,
    contribution_id: str,
    from_state: WorkflowState,
    to_state: WorkflowState,
    evidence: str,
    *,
    approval: Approval | None = None,
) -> None:
    """Validate ``from_state -> to_state`` and append the corresponding
    row to ``workflow_transitions``. Raises
    :class:`~opensource_scout.workflows.state_machine.InvalidTransitionError`
    or
    :class:`~opensource_scout.workflows.state_machine.ApprovalRequiredError`
    without writing anything if the transition isn't legal."""
    record = transition(contribution_id, from_state, to_state, evidence=evidence, approval=approval)
    session.add(
        WorkflowTransitionRow(
            contribution_id=contribution_id,
            from_state=record.from_state.value,
            to_state=record.to_state.value,
            evidence=record.evidence,
            occurred_at=record.at,
        )
    )
