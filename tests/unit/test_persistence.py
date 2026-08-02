from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from opensource_scout.db.models import ContributionRow, WorkflowTransitionRow
from opensource_scout.db.session import (
    build_engine,
    build_session_factory,
    create_schema,
    session_scope,
)


@pytest.fixture
def session_factory():
    engine = build_engine("sqlite:///:memory:")
    create_schema(engine)
    try:
        yield build_session_factory(engine)
    finally:
        engine.dispose()


def test_schema_creates_all_tables(session_factory) -> None:  # noqa: ANN001
    with session_scope(session_factory) as session:
        # A trivial query against each mapped table proves it exists.
        for model in (ContributionRow, WorkflowTransitionRow):
            session.execute(select(model)).all()


def test_contribution_round_trip(session_factory) -> None:  # noqa: ANN001
    now = datetime.now(UTC)
    with session_scope(session_factory) as session:
        session.add(
            ContributionRow(
                contribution_id="c1",
                repository_full_name="octo/example",
                state="PROJECT_SELECTED",
                created_at=now,
                updated_at=now,
            )
        )

    with session_scope(session_factory) as session:
        row = session.execute(
            select(ContributionRow).where(ContributionRow.contribution_id == "c1")
        ).scalar_one()
        assert row.repository_full_name == "octo/example"
        assert row.state == "PROJECT_SELECTED"


def test_workflow_transitions_are_resumable_by_replay(session_factory) -> None:  # noqa: ANN001
    now = datetime.now(UTC)
    with session_scope(session_factory) as session:
        session.add(
            ContributionRow(
                contribution_id="c2",
                repository_full_name="octo/example",
                state="PROFILE_READY",
                created_at=now,
                updated_at=now,
            )
        )
        session.add(
            WorkflowTransitionRow(
                contribution_id="c2",
                from_state="PROFILE_READY",
                to_state="PROJECT_DISCOVERY",
                evidence="started discovery",
            )
        )
        session.add(
            WorkflowTransitionRow(
                contribution_id="c2",
                from_state="PROJECT_DISCOVERY",
                to_state="PROJECT_SELECTED",
                evidence="selected octo/example",
            )
        )

    with session_scope(session_factory) as session:
        transitions = (
            session.execute(
                select(WorkflowTransitionRow)
                .where(WorkflowTransitionRow.contribution_id == "c2")
                .order_by(WorkflowTransitionRow.id)
            )
            .scalars()
            .all()
        )
        # Replaying the transition log reconstructs current state without
        # needing any additional recovery machinery.
        resumed_state = transitions[0].from_state
        for t in transitions:
            resumed_state = t.to_state
        assert resumed_state == "PROJECT_SELECTED"
        assert [t.to_state for t in transitions] == ["PROJECT_DISCOVERY", "PROJECT_SELECTED"]


def test_transaction_rolls_back_on_error(session_factory) -> None:  # noqa: ANN001
    now = datetime.now(UTC)
    with pytest.raises(RuntimeError), session_scope(session_factory) as session:
        session.add(
            ContributionRow(
                contribution_id="c3",
                repository_full_name="octo/example",
                state="PROFILE_READY",
                created_at=now,
                updated_at=now,
            )
        )
        raise RuntimeError("boom")

    with session_scope(session_factory) as session:
        result = session.execute(
            select(ContributionRow).where(ContributionRow.contribution_id == "c3")
        ).scalar_one_or_none()
        assert result is None
