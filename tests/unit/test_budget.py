from datetime import UTC, datetime, timedelta

import pytest

from opensource_scout.config import Settings
from opensource_scout.db.models import LlmCallRow
from opensource_scout.db.session import build_engine, build_session_factory, create_schema
from opensource_scout.llm.budget import (
    BudgetExceededError,
    check_budget,
    check_call_count,
    spend_this_month,
    spend_today,
)


@pytest.fixture
def session_factory():
    engine = build_engine("sqlite:///:memory:")
    create_schema(engine)
    try:
        yield build_session_factory(engine)
    finally:
        engine.dispose()


def _add_call(session_factory, *, cost: float, created_at: datetime) -> None:
    with session_factory() as session:
        session.add(
            LlmCallRow(
                task_category="x",
                model="gpt-4o",
                prompt_hash="h",
                estimated_cost_usd=cost,
                created_at=created_at,
            )
        )
        session.commit()


def test_spend_today_sums_only_todays_calls(session_factory) -> None:  # noqa: ANN001
    now = datetime(2026, 8, 2, 12, 0, tzinfo=UTC)
    _add_call(session_factory, cost=1.0, created_at=now)
    _add_call(session_factory, cost=2.0, created_at=now - timedelta(days=1))
    with session_factory() as session:
        spend = spend_today(session, now=now)
    assert spend.calls == 1
    assert spend.cost_usd == 1.0


def test_spend_this_month_sums_calls_since_first_of_month(session_factory) -> None:  # noqa: ANN001
    now = datetime(2026, 8, 15, tzinfo=UTC)
    _add_call(session_factory, cost=1.0, created_at=now)
    _add_call(session_factory, cost=2.0, created_at=datetime(2026, 8, 1, 1, tzinfo=UTC))
    _add_call(session_factory, cost=5.0, created_at=datetime(2026, 7, 31, tzinfo=UTC))
    with session_factory() as session:
        spend = spend_this_month(session, now=now)
    assert spend.calls == 2
    assert spend.cost_usd == 3.0


def test_check_budget_passes_when_under_limit(session_factory) -> None:  # noqa: ANN001
    settings = Settings(DAILY_OPENAI_BUDGET_USD=10.0, MONTHLY_OPENAI_BUDGET_USD=100.0)
    with session_factory() as session:
        check_budget(session, settings, estimated_additional_cost_usd=1.0)


def test_check_budget_raises_when_daily_limit_exceeded(session_factory) -> None:  # noqa: ANN001
    now = datetime.now(UTC)
    _add_call(session_factory, cost=4.99, created_at=now)
    settings = Settings(DAILY_OPENAI_BUDGET_USD=5.0, MONTHLY_OPENAI_BUDGET_USD=100.0)
    with session_factory() as session, pytest.raises(BudgetExceededError, match="daily"):
        check_budget(session, settings, estimated_additional_cost_usd=0.02, now=now)


def test_check_budget_raises_when_monthly_limit_exceeded(session_factory) -> None:  # noqa: ANN001
    now = datetime.now(UTC)
    _add_call(session_factory, cost=99.0, created_at=now)
    settings = Settings(DAILY_OPENAI_BUDGET_USD=1000.0, MONTHLY_OPENAI_BUDGET_USD=100.0)
    with session_factory() as session, pytest.raises(BudgetExceededError, match="monthly"):
        check_budget(session, settings, estimated_additional_cost_usd=2.0, now=now)


def test_check_call_count_passes_under_limit() -> None:
    settings = Settings(MAX_LLM_CALLS_PER_WORKFLOW=10)
    check_call_count(settings, 5)


def test_check_call_count_raises_at_limit() -> None:
    settings = Settings(MAX_LLM_CALLS_PER_WORKFLOW=10)
    with pytest.raises(BudgetExceededError):
        check_call_count(settings, 10)
