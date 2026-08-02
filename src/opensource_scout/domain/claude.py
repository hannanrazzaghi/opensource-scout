"""Domain model for Claude Pro's manually-imported review feedback.

Everything here is treated as untrusted input: parsed into structure so it
can be displayed and cross-checked, never executed. See
:mod:`opensource_scout.claude_bridge.import_` for the parser and
docs/security.md for why.
"""

from __future__ import annotations

from pydantic import BaseModel

_VALID_DECISIONS = frozenset({"APPROVE", "REVISE", "REJECT"})


class ClaudeReviewFeedback(BaseModel):
    decision: str
    critical_issues: tuple[str, ...] = ()
    suggested_improvements: tuple[str, ...] = ()
    missing_tests: tuple[str, ...] = ()
    rule_violations: tuple[str, ...] = ()
    recommended_next_step: str = ""
    raw_response: str

    @property
    def has_valid_decision(self) -> bool:
        return self.decision in _VALID_DECISIONS
