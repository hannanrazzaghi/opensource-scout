import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
import respx
from rich.console import Console
from sqlalchemy import select

from opensource_scout.config import Settings
from opensource_scout.db.models import ContributionRow, IssueRow, ProjectRow
from opensource_scout.db.session import build_session_factory, ensure_database
from opensource_scout.domain.enums import WorkflowState
from opensource_scout.reports.contribution_report import (
    contribution_id_for,
    run_contribution_implement,
    run_contribution_plan,
    run_contribution_status,
    run_contribution_validate,
    run_issue_reproduce,
)

_PLAN_PAYLOAD = {
    "problem": "ranking bug",
    "root_cause_hypothesis": "off by one",
    "proposed_changes": ["fix comparator"],
    "tests": ["test_ranking"],
    "alternatives": [],
    "risks": [],
    "estimated_hours": 2.0,
}


def _openai_response(payload: dict) -> dict:
    return {
        "id": "r1",
        "object": "response",
        "created_at": 0,
        "model": "gpt-4o-mini",
        "status": "completed",
        "output": [
            {
                "type": "message",
                "id": "m",
                "status": "completed",
                "role": "assistant",
                "content": [
                    {"type": "output_text", "text": json.dumps(payload), "annotations": []}
                ],
            }
        ],
        "usage": {
            "input_tokens": 10,
            "output_tokens": 10,
            "total_tokens": 20,
            "output_tokens_details": {"reasoning_tokens": 0},
            "input_tokens_details": {"cached_tokens": 0},
        },
        "parallel_tool_calls": True,
        "tool_choice": "auto",
        "tools": [],
    }


def test_issue_reproduce_requires_selection_first(tmp_path: Path) -> None:
    settings = Settings(OSS_DATA_DIR=tmp_path)
    console = Console()
    run_issue_reproduce(settings, "octo/example", 1, console=console, clone_url="file:///nope")

    engine = ensure_database(settings.database_path, settings.database_url)
    with build_session_factory(engine)() as session:
        row = session.execute(select(ContributionRow)).scalar_one_or_none()
        assert row is None  # never created — selection check short-circuited first


def test_issue_reproduce_advances_workflow_and_persists_report(
    tmp_path: Path, local_git_repo
) -> None:
    src = local_git_repo({"test_ok.py": "def test_passes():\n    assert True\n"})
    settings = Settings(OSS_DATA_DIR=tmp_path)
    engine = ensure_database(settings.database_path, settings.database_url)
    session_factory = build_session_factory(engine)
    repo = "octo/example"

    with session_factory() as session:
        session.add(ProjectRow(full_name=repo, url="x", selected=True, metadata_json={}))
        session.add(
            IssueRow(repository_full_name=repo, number=1, title="t", url="x", selected=True)
        )
        session.commit()

    run_issue_reproduce(settings, repo, 1, console=Console(), clone_url=f"file://{src}")

    cid = contribution_id_for(repo, 1)
    with session_factory() as session:
        row = session.execute(
            select(ContributionRow).where(ContributionRow.contribution_id == cid)
        ).scalar_one()
        assert row.state == WorkflowState.ISSUE_REPRODUCED.value
        assert row.extra_json["reproduction_report"]["status"] == "NEEDS_CLARIFICATION"


@pytest.mark.respx(base_url="https://api.openai.com")
def test_full_plan_implement_validate_chain(respx_mock: respx.MockRouter, tmp_path: Path) -> None:
    respx_mock.post("/v1/responses").mock(
        return_value=httpx.Response(200, json=_openai_response(_PLAN_PAYLOAD))
    )

    settings = Settings(OSS_DATA_DIR=tmp_path, OPENAI_MODEL_REASONING="gpt-4o-mini")
    engine = ensure_database(settings.database_path, settings.database_url)
    session_factory = build_session_factory(engine)
    repo = "octo/example"
    cid = contribution_id_for(repo, 1)
    now = datetime.now(UTC)

    with session_factory() as session:
        session.add(ProjectRow(full_name=repo, url="x", selected=True, metadata_json={}))
        session.add(
            IssueRow(
                repository_full_name=repo,
                number=1,
                title="Fix ranking bug",
                url="x",
                selected=True,
                metadata_json={"body": "ranking is wrong"},
            )
        )
        session.add(
            ContributionRow(
                contribution_id=cid,
                repository_full_name=repo,
                issue_number=1,
                state=WorkflowState.ISSUE_REPRODUCED.value,
                base_commit_sha="abc123",
                created_at=now,
                updated_at=now,
            )
        )
        session.commit()

    console = Console()
    run_contribution_plan(settings, f"{repo}#1", console=console)

    with session_factory() as session:
        row = session.execute(
            select(ContributionRow).where(ContributionRow.contribution_id == cid)
        ).scalar_one()
        assert row.state == WorkflowState.IMPLEMENTATION_PLANNED.value
        assert row.extra_json["implementation_plan"]["problem"] == "ranking bug"

    run_contribution_implement(settings, cid, console=console)
    with session_factory() as session:
        row = session.execute(
            select(ContributionRow).where(ContributionRow.contribution_id == cid)
        ).scalar_one()
        assert row.state == WorkflowState.IMPLEMENTING.value

    run_contribution_validate(settings, cid, console=console)
    with session_factory() as session:
        row = session.execute(
            select(ContributionRow).where(ContributionRow.contribution_id == cid)
        ).scalar_one()
        # no test command was extractable (no rules stored), so validation
        # has nothing to run and the contribution stays in IMPLEMENTING
        assert row.state == WorkflowState.IMPLEMENTING.value

    run_contribution_status(settings, cid, console=console)  # must not raise


def test_plan_rejects_contribution_not_yet_reproduced(tmp_path: Path) -> None:
    settings = Settings(OSS_DATA_DIR=tmp_path)
    ensure_database(settings.database_path, settings.database_url)
    console = Console()
    run_contribution_plan(settings, "octo/example#99", console=console)  # must not raise
