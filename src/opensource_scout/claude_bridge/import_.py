"""Parse Claude Pro's pasted-back review response into structured,
untrusted feedback.

Named ``import_`` (trailing underscore) because ``import`` is a Python
keyword and can't be a module name; the CLI command is still `oss claude
import`.

The parsed result is never executed and never trusted at face value —
callers are expected to verify any factual claim (e.g. "tests are missing")
against the repository before acting on it. Only the fixed section headers
defined in the export packet's "Requested response format" are recognized;
anything else in the file is preserved in ``raw_response`` but not parsed
into a specific field.
"""

from __future__ import annotations

import re

from opensource_scout.domain.claude import ClaudeReviewFeedback

_DECISION_PATTERN = re.compile(r"(?im)^DECISION:\s*(APPROVE|REVISE|REJECT)\s*$")
_SECTION_PATTERN = re.compile(
    r"(?im)^(CRITICAL ISSUES|SUGGESTED IMPROVEMENTS|MISSING TESTS|RULE VIOLATIONS):\s*$"
)
_NEXT_STEP_PATTERN = re.compile(r"(?ims)^RECOMMENDED NEXT STEP:\s*\n(.*?)(?:\n\n|\Z)")
_BULLET_PATTERN = re.compile(r"^\s*-\s*(.+)$", re.MULTILINE)

_SECTION_FIELD_MAP = {
    "CRITICAL ISSUES": "critical_issues",
    "SUGGESTED IMPROVEMENTS": "suggested_improvements",
    "MISSING TESTS": "missing_tests",
    "RULE VIOLATIONS": "rule_violations",
}


class ClaudeImportError(Exception):
    """Raised when a response file doesn't contain a recognizable
    ``DECISION:`` line — the one required piece of structure."""


def _extract_bullets(text: str, start: int, end: int) -> tuple[str, ...]:
    section_text = text[start:end]
    bullets = [m.group(1).strip() for m in _BULLET_PATTERN.finditer(section_text)]
    return tuple(b for b in bullets if b and b != "...")


def parse_claude_review(raw_response: str) -> ClaudeReviewFeedback:
    """Parse a Claude response matching the fixed template. Raises
    :class:`ClaudeImportError` if no ``DECISION:`` line is found — anything
    else is treated as untrusted, best-effort structure with sensible
    defaults for missing sections."""
    decision_match = _DECISION_PATTERN.search(raw_response)
    if decision_match is None:
        raise ClaudeImportError(
            "no recognizable 'DECISION: APPROVE|REVISE|REJECT' line found — "
            "this doesn't look like a response to an OpenSourceScout review packet"
        )

    section_starts: list[tuple[str, int]] = [
        (m.group(1).upper(), m.end()) for m in _SECTION_PATTERN.finditer(raw_response)
    ]
    section_bounds: dict[str, tuple[int, int]] = {}
    for i, (name, start) in enumerate(section_starts):
        end = section_starts[i + 1][1] if i + 1 < len(section_starts) else len(raw_response)
        # Trim the end back to just before the next section's header line.
        if i + 1 < len(section_starts):
            next_header_start = raw_response.rfind("\n", 0, end)
            end = next_header_start if next_header_start != -1 else end
        section_bounds[name] = (start, end)

    fields: dict[str, tuple[str, ...]] = {}
    for header, field_name in _SECTION_FIELD_MAP.items():
        if header in section_bounds:
            start, end = section_bounds[header]
            fields[field_name] = _extract_bullets(raw_response, start, end)
        else:
            fields[field_name] = ()

    next_step_match = _NEXT_STEP_PATTERN.search(raw_response)
    recommended_next_step = next_step_match.group(1).strip() if next_step_match else ""
    if recommended_next_step == "...":
        recommended_next_step = ""

    return ClaudeReviewFeedback(
        decision=decision_match.group(1).upper(),
        critical_issues=fields["critical_issues"],
        suggested_improvements=fields["suggested_improvements"],
        missing_tests=fields["missing_tests"],
        rule_violations=fields["rule_violations"],
        recommended_next_step=recommended_next_step,
        raw_response=raw_response,
    )
