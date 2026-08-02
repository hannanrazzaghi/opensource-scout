"""Cost and call-count budget enforcement.

Every check here happens *before* a request is made — this module exists so
a runaway loop can't blow through a daily or monthly spend cap, not to
produce a nicer post-hoc report. All figures are read from the ``llm_calls``
table, which is the single source of truth for what was actually spent (see
:mod:`opensource_scout.llm.client` for where rows are written).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from opensource_scout.config import Settings
from opensource_scout.db.models import LlmCallRow


class BudgetExceededError(Exception):
    """Raised when a call would exceed the configured daily/monthly budget
    or the per-workflow call-count limit. Callers must not retry with a
    smaller request to sneak under the cap — the run should stop and let a
    human decide whether to raise the budget."""


@dataclass(frozen=True)
class Spend:
    calls: int
    cost_usd: float


def _sum_since(session: Session, since: datetime) -> Spend:
    row = session.execute(
        select(
            func.count(LlmCallRow.id), func.coalesce(func.sum(LlmCallRow.estimated_cost_usd), 0.0)
        ).where(LlmCallRow.created_at >= since)
    ).one()
    return Spend(calls=row[0], cost_usd=float(row[1]))


def spend_today(session: Session, *, now: datetime | None = None) -> Spend:
    at = now or datetime.now(UTC)
    start_of_day = at.replace(hour=0, minute=0, second=0, microsecond=0)
    return _sum_since(session, start_of_day)


def spend_this_month(session: Session, *, now: datetime | None = None) -> Spend:
    at = now or datetime.now(UTC)
    start_of_month = at.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return _sum_since(session, start_of_month)


def check_budget(
    session: Session,
    settings: Settings,
    *,
    estimated_additional_cost_usd: float = 0.0,
    now: datetime | None = None,
) -> None:
    """Raise :class:`BudgetExceededError` if today's or this month's spend,
    plus the estimated cost of the call about to be made, would exceed the
    configured budget."""
    today = spend_today(session, now=now)
    if today.cost_usd + estimated_additional_cost_usd > settings.daily_openai_budget_usd:
        raise BudgetExceededError(
            f"daily OpenAI budget exceeded: "
            f"${today.cost_usd:.4f} spent + ${estimated_additional_cost_usd:.4f} estimated "
            f"> ${settings.daily_openai_budget_usd:.2f} limit"
        )

    month = spend_this_month(session, now=now)
    if month.cost_usd + estimated_additional_cost_usd > settings.monthly_openai_budget_usd:
        raise BudgetExceededError(
            f"monthly OpenAI budget exceeded: "
            f"${month.cost_usd:.4f} spent + ${estimated_additional_cost_usd:.4f} estimated "
            f"> ${settings.monthly_openai_budget_usd:.2f} limit"
        )


def check_call_count(settings: Settings, calls_this_workflow: int) -> None:
    if calls_this_workflow >= settings.max_llm_calls_per_workflow:
        raise BudgetExceededError(
            f"workflow call limit reached: {calls_this_workflow} "
            f">= {settings.max_llm_calls_per_workflow} max calls per workflow"
        )
