"""Routes LLM calls to one of three logical roles — fast, reasoning, coding —
rather than hard-coding model names anywhere in application code.

The same underlying model may serve multiple roles (a user with only one
model available can point all three at it); what this module guarantees is
that a role never silently upgrades to a different, possibly more expensive
model just because its configured one failed. That's a fail-loud decision,
not a fail-soft one — cost predictability matters more than availability
here.
"""

from __future__ import annotations

from enum import StrEnum

from opensource_scout.config import Settings


class ModelRole(StrEnum):
    """See docs/architecture.md for what each role is used for:
    FAST for classification/triage/extraction, REASONING for comparisons and
    ambiguous analysis, CODING for patches/tests/PR drafting."""

    FAST = "fast"
    REASONING = "reasoning"
    CODING = "coding"


class ModelUnavailableError(Exception):
    """Raised when the model configured for a role is missing or blank.
    Callers must not catch this and fall back to a different role's model —
    that would be exactly the silent-upgrade behavior this module exists to
    prevent."""


def resolve_model(settings: Settings, role: ModelRole) -> str:
    model = {
        ModelRole.FAST: settings.openai_model_fast,
        ModelRole.REASONING: settings.openai_model_reasoning,
        ModelRole.CODING: settings.openai_model_coding,
    }[role]
    if not model or not model.strip():
        raise ModelUnavailableError(f"no model configured for role {role.value!r}")
    return model
