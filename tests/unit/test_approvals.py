from datetime import UTC, datetime, timedelta

import pytest

from opensource_scout.approvals.service import (
    ApprovalError,
    consume_approval,
    find_valid_approval,
    grant_approval,
    request_approval,
)
from opensource_scout.db.models import ContributionRow
from opensource_scout.db.session import build_engine, build_session_factory, create_schema
from opensource_scout.domain.enums import ApprovalKind, WorkflowState


@pytest.fixture
def session_factory():
    engine = build_engine("sqlite:///:memory:")
    create_schema(engine)
    try:
        yield build_session_factory(engine)
    finally:
        engine.dispose()


@pytest.fixture
def contribution_id(session_factory) -> str:  # noqa: ANN001
    now = datetime.now(UTC)
    with session_factory() as session:
        session.add(
            ContributionRow(
                contribution_id="c1",
                repository_full_name="octo/example",
                state=WorkflowState.AWAITING_PUSH_APPROVAL.value,
                created_at=now,
                updated_at=now,
            )
        )
        session.commit()
    return "c1"


def test_request_approval_does_not_create_a_valid_approval(
    session_factory, contribution_id
) -> None:  # noqa: ANN001
    with session_factory() as session:
        request_approval(session, contribution_id, ApprovalKind.PUSH_EXTERNAL_BRANCH)
        session.commit()

    with session_factory() as session:
        assert (
            find_valid_approval(session, contribution_id, ApprovalKind.PUSH_EXTERNAL_BRANCH) is None
        )


def test_grant_approval_makes_it_valid(session_factory, contribution_id) -> None:  # noqa: ANN001
    with session_factory() as session:
        approval_id = request_approval(session, contribution_id, ApprovalKind.PUSH_EXTERNAL_BRANCH)
        session.commit()

    with session_factory() as session:
        granted = grant_approval(session, approval_id)
        session.commit()
        assert granted.contribution_id == contribution_id
        assert granted.kind is ApprovalKind.PUSH_EXTERNAL_BRANCH

    with session_factory() as session:
        found = find_valid_approval(session, contribution_id, ApprovalKind.PUSH_EXTERNAL_BRANCH)
        assert found is not None
        assert found.approval_id == approval_id


def test_grant_approval_removes_it_from_pending(session_factory, contribution_id) -> None:  # noqa: ANN001
    with session_factory() as session:
        approval_id = request_approval(session, contribution_id, ApprovalKind.PUSH_EXTERNAL_BRANCH)
        session.commit()

    with session_factory() as session:
        grant_approval(session, approval_id)
        session.commit()

    with session_factory() as session, pytest.raises(ApprovalError):
        grant_approval(session, approval_id)  # no longer pending


def test_grant_unknown_approval_id_raises(session_factory) -> None:  # noqa: ANN001
    with session_factory() as session, pytest.raises(ApprovalError):
        grant_approval(session, "does-not-exist")


def test_consume_approval_makes_it_invalid(session_factory, contribution_id) -> None:  # noqa: ANN001
    with session_factory() as session:
        approval_id = request_approval(session, contribution_id, ApprovalKind.PUSH_EXTERNAL_BRANCH)
        grant_approval(session, approval_id)
        session.commit()

    with session_factory() as session:
        consume_approval(session, approval_id)
        session.commit()

    with session_factory() as session:
        assert (
            find_valid_approval(session, contribution_id, ApprovalKind.PUSH_EXTERNAL_BRANCH) is None
        )


def test_consume_unknown_approval_raises(session_factory) -> None:  # noqa: ANN001
    with session_factory() as session, pytest.raises(ApprovalError):
        consume_approval(session, "does-not-exist")


def test_expired_approval_is_not_valid(session_factory, contribution_id) -> None:  # noqa: ANN001
    with session_factory() as session:
        approval_id = request_approval(session, contribution_id, ApprovalKind.PUSH_EXTERNAL_BRANCH)
        grant_approval(session, approval_id, window=timedelta(seconds=-1))
        session.commit()

    with session_factory() as session:
        assert (
            find_valid_approval(session, contribution_id, ApprovalKind.PUSH_EXTERNAL_BRANCH) is None
        )


def test_wrong_kind_is_not_returned(session_factory, contribution_id) -> None:  # noqa: ANN001
    with session_factory() as session:
        approval_id = request_approval(session, contribution_id, ApprovalKind.PUSH_EXTERNAL_BRANCH)
        grant_approval(session, approval_id)
        session.commit()

    with session_factory() as session:
        found = find_valid_approval(
            session, contribution_id, ApprovalKind.OPEN_EXTERNAL_PULL_REQUEST
        )
        assert found is None
