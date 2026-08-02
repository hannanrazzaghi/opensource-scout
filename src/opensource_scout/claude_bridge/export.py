"""Export Markdown review packets for the Claude Pro manual review loop.

Claude Pro is never called programmatically (there is no Anthropic API key
in this project) — a packet is written to disk for the user to paste into
Claude, and the response is later parsed back in by
:mod:`opensource_scout.claude_bridge.import_`. See docs/security.md for the
reasoning behind treating Claude's response as untrusted input.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from opensource_scout.db.models import ContributionRow, IssueRow, ProjectRow
from opensource_scout.domain.profile import HANNAN_PROFILE

ReviewType = Literal["architecture", "issue", "plan", "diff", "pr"]

_REQUESTED_FORMAT = """\
DECISION: APPROVE | REVISE | REJECT

CRITICAL ISSUES:
- ...

SUGGESTED IMPROVEMENTS:
- ...

MISSING TESTS:
- ...

RULE VIOLATIONS:
- ...

RECOMMENDED NEXT STEP:
...
"""


class ClaudeExportError(Exception):
    """Raised when the requested review type or ID can't be exported
    (e.g. no such contribution)."""


def _profile_summary() -> str:
    p = HANNAN_PROFILE
    return (
        f"{p.name} ({p.github_username}) — {p.operating_system}/{p.hardware}, "
        f"{p.weekly_hours_min}-{p.weekly_hours_max}h/week. "
        f"Skills: {', '.join(p.skills[:8])}..."
    )


def _repository_rules_section(project_row: ProjectRow | None) -> str:
    if project_row is None:
        return "(no repository rules extracted yet)"
    rules = (project_row.metadata_json or {}).get("contribution_rules", [])
    if not rules:
        return "(no repository rules extracted yet)"
    lines = [
        f"- [{r['category']}] {r['file_path']} ({r['heading_or_range']}): {r['excerpt']}"
        for r in rules
    ]
    return "\n".join(lines)


def _build_packet(
    *,
    review_type: ReviewType,
    review_question: str,
    contribution: ContributionRow | None,
    issue_row: IssueRow | None,
    project_row: ProjectRow | None,
) -> str:
    extra = (contribution.extra_json or {}) if contribution else {}
    plan = extra.get("implementation_plan")
    validation = extra.get("validation_results", [])
    reproduction = extra.get("reproduction_report")

    sections = [
        f"# Claude Pro review packet — {review_type}",
        "",
        f"Generated: {datetime.now(UTC).isoformat()}",
        "",
        "## Review question",
        review_question,
        "",
        "## User profile",
        _profile_summary(),
        "",
        "## Repository rules",
        _repository_rules_section(project_row),
        "",
    ]

    if issue_row is not None:
        sections += [
            "## Issue summary",
            f"{issue_row.repository_full_name}#{issue_row.number}: {issue_row.title}",
            (issue_row.metadata_json or {}).get("body", "")[:2000],
            "",
        ]

    if reproduction is not None:
        sections += [
            "## Reproduction evidence",
            f"Status: {reproduction['status']}",
            reproduction["summary"],
            "",
        ]

    if plan is not None:
        sections += [
            "## Proposed plan",
            f"Problem: {plan['problem']}",
            f"Root cause hypothesis: {plan['root_cause_hypothesis']}",
            "Proposed changes:",
            *[f"- {c}" for c in plan["proposed_changes"]],
            "Tests:",
            *[f"- {t}" for t in plan["tests"]],
            f"Estimated hours: {plan['estimated_hours']}",
            "",
        ]

    sections += [
        "## Diff",
        (
            "(OpenSourceScout does not write code to disk automatically — "
            "paste the actual diff here before sending to Claude.)"
            if review_type in ("diff", "pr")
            else "(not applicable to this review type)"
        ),
        "",
        "## Test evidence",
        "\n".join(f"- {r['command']}: {r['status']}" for r in validation) or "(none recorded yet)",
        "",
        "## Known uncertainties",
        "- This packet was generated automatically; verify all claims against the repository.",
        "",
        "## Requested response format",
        "```",
        _REQUESTED_FORMAT,
        "```",
    ]
    return "\n".join(sections)


def export_review_packet(
    session: Session,
    output_dir: Path,
    review_type: ReviewType,
    identifier: str,
) -> Path:
    """Write a review packet to ``output_dir`` and return its path.

    ``identifier`` is a contribution ID for plan/diff/pr, an
    ``owner/repo#number`` issue reference for issue, or ignored for
    architecture.
    """
    contribution: ContributionRow | None = None
    issue_row: IssueRow | None = None
    project_row: ProjectRow | None = None
    review_question = {
        "architecture": "Review the overall architecture approach for this project.",
        "issue": "Is this issue a good, well-scoped target for a first contribution?",
        "plan": "Review this implementation plan for correctness and completeness.",
        "diff": "Review this diff for correctness, style, and rule compliance.",
        "pr": "Review this pull request description for accuracy and clarity.",
    }[review_type]

    if review_type == "issue":
        if "#" not in identifier:
            raise ClaudeExportError(f"expected owner/repository#number, got {identifier!r}")
        repository, _, number_str = identifier.rpartition("#")
        issue_row = session.execute(
            select(IssueRow).where(
                IssueRow.repository_full_name == repository, IssueRow.number == int(number_str)
            )
        ).scalar_one_or_none()
        if issue_row is None:
            raise ClaudeExportError(f"no discovered issue {identifier!r}")
        project_row = session.execute(
            select(ProjectRow).where(ProjectRow.full_name == repository)
        ).scalar_one_or_none()
    elif review_type != "architecture":
        contribution = session.execute(
            select(ContributionRow).where(ContributionRow.contribution_id == identifier)
        ).scalar_one_or_none()
        if contribution is None:
            raise ClaudeExportError(f"no contribution {identifier!r}")
        project_row = session.execute(
            select(ProjectRow).where(ProjectRow.full_name == contribution.repository_full_name)
        ).scalar_one_or_none()

    packet = _build_packet(
        review_type=review_type,
        review_question=review_question,
        contribution=contribution,
        issue_row=issue_row,
        project_row=project_row,
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    safe_id = identifier.replace("/", "-").replace("#", "-")
    path = output_dir / f"{review_type}-{safe_id}.md"
    path.write_text(packet, encoding="utf-8")
    return path
