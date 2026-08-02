import subprocess
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
import respx
from rich.console import Console
from sqlalchemy import select

from opensource_scout.approvals.service import grant_approval
from opensource_scout.config import Settings
from opensource_scout.db.models import ContributionRow
from opensource_scout.db.session import build_session_factory, ensure_database
from opensource_scout.domain.enums import WorkflowState
from opensource_scout.reports.pr_report import run_github_open_pr, run_github_push, run_pr_prepare


def _bare_remote(tmp_path: Path) -> Path:
    remote = tmp_path / "remote.git"
    remote.mkdir()
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main"], cwd=remote, check=True)
    return remote


def _seeded_workspace(settings: Settings, contribution_id: str, remote: Path) -> Path:
    workspace = settings.workspace_dir / contribution_id
    subprocess.run(["git", "clone", "-q", f"file://{remote}", str(workspace)], check=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=workspace, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=workspace, check=True)
    (workspace / "README.md").write_text("initial\n")
    subprocess.run(["git", "add", "."], cwd=workspace, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=workspace, check=True)
    subprocess.run(["git", "push", "-q", "origin", "main"], cwd=workspace, check=True)
    (workspace / "fix.py").write_text("x = 1\n")
    subprocess.run(["git", "add", "."], cwd=workspace, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "fix"], cwd=workspace, check=True)
    return workspace


def _seed_contribution(settings: Settings, contribution_id: str) -> None:
    engine = ensure_database(settings.database_path, settings.database_url)
    session_factory = build_session_factory(engine)
    now = datetime.now(UTC)
    with session_factory() as session:
        session.add(
            ContributionRow(
                contribution_id=contribution_id,
                repository_full_name="octo/example",
                issue_number=1,
                state=WorkflowState.PR_PREPARED.value,
                created_at=now,
                updated_at=now,
                extra_json={
                    "implementation_plan": {
                        "problem": "off by one in ranking",
                        "root_cause_hypothesis": "index error",
                        "proposed_changes": ["fix index"],
                        "tests": ["test_ranking"],
                        "estimated_hours": 1.0,
                    },
                    "validation_results": [{"command": "test: pytest", "status": "PASSED"}],
                },
            )
        )
        session.commit()


def test_pr_prepare_requests_push_approval(tmp_path: Path) -> None:
    remote = _bare_remote(tmp_path)
    settings = Settings(OSS_DATA_DIR=tmp_path / "data")
    cid = "octo-example-1"
    _seeded_workspace(settings, cid, remote)
    _seed_contribution(settings, cid)

    run_pr_prepare(settings, cid, console=Console())

    engine = ensure_database(settings.database_path, settings.database_url)
    session_factory = build_session_factory(engine)
    with session_factory() as session:
        row = session.execute(
            select(ContributionRow).where(ContributionRow.contribution_id == cid)
        ).scalar_one()
        assert row.state == WorkflowState.AWAITING_PUSH_APPROVAL.value
        assert row.extra_json["pr_prep"]["branch_name"]
        assert len(row.extra_json["pending_approvals"]) == 1


def test_push_is_blocked_without_a_valid_approval(tmp_path: Path) -> None:
    remote = _bare_remote(tmp_path)
    settings = Settings(OSS_DATA_DIR=tmp_path / "data")
    cid = "octo-example-1"
    _seeded_workspace(settings, cid, remote)
    _seed_contribution(settings, cid)

    console = Console()
    run_pr_prepare(settings, cid, console=console)
    run_github_push(settings, cid, dry_run=False, console=console)

    engine = ensure_database(settings.database_path, settings.database_url)
    session_factory = build_session_factory(engine)
    with session_factory() as session:
        row = session.execute(
            select(ContributionRow).where(ContributionRow.contribution_id == cid)
        ).scalar_one()
        assert row.state == WorkflowState.AWAITING_PUSH_APPROVAL.value  # unchanged


def test_push_dry_run_does_not_push_or_change_state(tmp_path: Path) -> None:
    remote = _bare_remote(tmp_path)
    settings = Settings(OSS_DATA_DIR=tmp_path / "data")
    cid = "octo-example-1"
    _seeded_workspace(settings, cid, remote)
    _seed_contribution(settings, cid)

    console = Console()
    run_pr_prepare(settings, cid, console=console)
    run_github_push(settings, cid, dry_run=True, console=console)

    refs = subprocess.run(
        ["git", "for-each-ref", "refs/heads"],
        cwd=remote,
        capture_output=True,
        text=True,
        check=True,
    )
    assert "oss/" not in refs.stdout


@pytest.mark.respx(base_url="https://api.github.com")
def test_full_push_and_open_pr_chain(respx_mock: respx.MockRouter, tmp_path: Path) -> None:
    respx_mock.post("/repos/octo/example/pulls").mock(
        return_value=httpx.Response(
            201, json={"number": 7, "html_url": "https://github.com/octo/example/pull/7"}
        )
    )

    remote = _bare_remote(tmp_path)
    settings = Settings(OSS_DATA_DIR=tmp_path / "data")
    cid = "octo-example-1"
    _seeded_workspace(settings, cid, remote)
    _seed_contribution(settings, cid)

    engine = ensure_database(settings.database_path, settings.database_url)
    session_factory = build_session_factory(engine)
    console = Console()

    run_pr_prepare(settings, cid, console=console)
    with session_factory() as session:
        row = session.execute(
            select(ContributionRow).where(ContributionRow.contribution_id == cid)
        ).scalar_one()
        push_approval_id = row.extra_json["pending_approvals"][0]["approval_id"]
        branch_name = row.extra_json["pr_prep"]["branch_name"]

    with session_factory() as session:
        grant_approval(session, push_approval_id)
        session.commit()

    run_github_push(settings, cid, dry_run=False, console=console)
    with session_factory() as session:
        row = session.execute(
            select(ContributionRow).where(ContributionRow.contribution_id == cid)
        ).scalar_one()
        assert row.state == WorkflowState.BRANCH_PUSHED.value

    refs = subprocess.run(
        ["git", "for-each-ref", "refs/heads"],
        cwd=remote,
        capture_output=True,
        text=True,
        check=True,
    )
    assert branch_name in refs.stdout

    # first open-pr call only requests approval
    run_github_open_pr(settings, cid, dry_run=False, console=console)
    with session_factory() as session:
        row = session.execute(
            select(ContributionRow).where(ContributionRow.contribution_id == cid)
        ).scalar_one()
        assert row.state == WorkflowState.AWAITING_PR_APPROVAL.value
        pr_approval_id = row.extra_json["pending_approvals"][0]["approval_id"]

    with session_factory() as session:
        grant_approval(session, pr_approval_id)
        session.commit()

    run_github_open_pr(settings, cid, dry_run=False, console=console)
    with session_factory() as session:
        row = session.execute(
            select(ContributionRow).where(ContributionRow.contribution_id == cid)
        ).scalar_one()
        assert row.state == WorkflowState.PR_OPENED.value
        assert row.pull_request_url == "https://github.com/octo/example/pull/7"
