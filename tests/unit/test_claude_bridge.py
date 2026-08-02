from datetime import UTC, datetime
from pathlib import Path

import pytest

from opensource_scout.claude_bridge.export import ClaudeExportError, export_review_packet
from opensource_scout.claude_bridge.import_ import ClaudeImportError, parse_claude_review
from opensource_scout.db.models import ContributionRow
from opensource_scout.db.session import build_engine, build_session_factory, create_schema


@pytest.fixture
def session_factory():
    engine = build_engine("sqlite:///:memory:")
    create_schema(engine)
    try:
        yield build_session_factory(engine)
    finally:
        engine.dispose()


def test_export_architecture_packet_needs_no_id(session_factory, tmp_path: Path) -> None:  # noqa: ANN001
    with session_factory() as session:
        path = export_review_packet(session, tmp_path, "architecture", "n/a")
    content = path.read_text()
    assert "Claude Pro review packet — architecture" in content
    assert "DECISION: APPROVE | REVISE | REJECT" in content


def test_export_plan_packet_includes_stored_plan(session_factory, tmp_path: Path) -> None:  # noqa: ANN001
    now = datetime.now(UTC)
    with session_factory() as session:
        session.add(
            ContributionRow(
                contribution_id="c1",
                repository_full_name="octo/example",
                state="IMPLEMENTATION_PLANNED",
                created_at=now,
                updated_at=now,
                extra_json={
                    "implementation_plan": {
                        "problem": "ranking bug",
                        "root_cause_hypothesis": "off by one",
                        "proposed_changes": ["fix comparator"],
                        "tests": ["test_ranking"],
                        "estimated_hours": 2.0,
                    }
                },
            )
        )
        session.commit()

    with session_factory() as session:
        path = export_review_packet(session, tmp_path, "plan", "c1")
    content = path.read_text()
    assert "ranking bug" in content
    assert "fix comparator" in content


def test_export_unknown_contribution_raises(session_factory, tmp_path: Path) -> None:  # noqa: ANN001
    with session_factory() as session, pytest.raises(ClaudeExportError):
        export_review_packet(session, tmp_path, "plan", "nonexistent")


def test_export_issue_without_hash_raises(session_factory, tmp_path: Path) -> None:  # noqa: ANN001
    with session_factory() as session, pytest.raises(ClaudeExportError):
        export_review_packet(session, tmp_path, "issue", "octo/example")


def test_parse_full_response() -> None:
    response = """DECISION: REVISE

CRITICAL ISSUES:
- Root cause hypothesis unverified
- Missing null check

SUGGESTED IMPROVEMENTS:
- Add a docstring

MISSING TESTS:
- test_edge_case

RULE VIOLATIONS:
- none

RECOMMENDED NEXT STEP:
Add the missing null check and re-run validation.
"""
    feedback = parse_claude_review(response)
    assert feedback.decision == "REVISE"
    assert feedback.critical_issues == (
        "Root cause hypothesis unverified",
        "Missing null check",
    )
    assert feedback.suggested_improvements == ("Add a docstring",)
    assert feedback.missing_tests == ("test_edge_case",)
    assert feedback.rule_violations == ("none",)
    assert feedback.recommended_next_step == "Add the missing null check and re-run validation."
    assert feedback.raw_response == response


def test_parse_unfilled_template_yields_empty_fields() -> None:
    response = (
        "DECISION: APPROVE\n\n"
        "CRITICAL ISSUES:\n- ...\n\n"
        "SUGGESTED IMPROVEMENTS:\n- ...\n\n"
        "MISSING TESTS:\n- ...\n\n"
        "RULE VIOLATIONS:\n- ...\n\n"
        "RECOMMENDED NEXT STEP:\n...\n"
    )
    feedback = parse_claude_review(response)
    assert feedback.decision == "APPROVE"
    assert feedback.critical_issues == ()
    assert feedback.recommended_next_step == ""


def test_parse_missing_decision_raises() -> None:
    with pytest.raises(ClaudeImportError):
        parse_claude_review("This is not a valid response at all.")


def test_parse_is_case_insensitive_for_decision_keyword() -> None:
    response = "decision: approve\n"
    feedback = parse_claude_review(response)
    assert feedback.decision == "APPROVE"


def test_has_valid_decision_property() -> None:
    feedback = parse_claude_review("DECISION: REJECT\n")
    assert feedback.has_valid_decision is True
