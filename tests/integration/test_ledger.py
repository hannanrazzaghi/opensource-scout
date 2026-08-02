from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
import respx
from rich.console import Console
from sqlalchemy import select

from opensource_scout.config import Settings
from opensource_scout.db.models import ContributionRow
from opensource_scout.db.session import build_session_factory, ensure_database
from opensource_scout.domain.enums import WorkflowState
from opensource_scout.reports.ledger_report import (
    run_ledger_list,
    run_ledger_show,
    run_ledger_sync,
    run_resume_generate,
)


def _seed(settings: Settings, contribution_id: str, state: str, *, pr_url: str | None) -> None:
    engine = ensure_database(settings.database_path, settings.database_url)
    session_factory = build_session_factory(engine)
    now = datetime.now(UTC)
    with session_factory() as session:
        session.add(
            ContributionRow(
                contribution_id=contribution_id,
                repository_full_name="octo/example",
                issue_number=1,
                state=state,
                pull_request_url=pr_url,
                created_at=now,
                updated_at=now,
                extra_json={
                    "implementation_plan": {
                        "problem": "Python ranking bug",
                        "root_cause_hypothesis": "BM25 off by one",
                    }
                },
            )
        )
        session.commit()


def test_ledger_list_shows_nothing_initially(tmp_path: Path) -> None:
    settings = Settings(OSS_DATA_DIR=tmp_path)
    ensure_database(settings.database_path, settings.database_url)
    run_ledger_list(settings, console=Console())  # must not raise


def test_ledger_show_unknown_contribution(tmp_path: Path) -> None:
    settings = Settings(OSS_DATA_DIR=tmp_path)
    ensure_database(settings.database_path, settings.database_url)
    run_ledger_show(settings, "nonexistent", console=Console())  # must not raise


def test_resume_generate_blocked_before_merge(tmp_path: Path) -> None:
    settings = Settings(OSS_DATA_DIR=tmp_path)
    cid = "octo-example-1"
    _seed(
        settings,
        cid,
        WorkflowState.PR_OPENED.value,
        pr_url="https://github.com/octo/example/pull/7",
    )

    run_resume_generate(settings, cid, console=Console())

    engine = ensure_database(settings.database_path, settings.database_url)
    session_factory = build_session_factory(engine)
    with session_factory() as session:
        row = session.execute(
            select(ContributionRow).where(ContributionRow.contribution_id == cid)
        ).scalar_one()
        assert row.resume_bullet is None


@pytest.mark.respx(base_url="https://api.github.com")
def test_ledger_sync_advances_state_on_merge(respx_mock: respx.MockRouter, tmp_path: Path) -> None:
    respx_mock.get("/repos/octo/example/pulls/7").mock(
        return_value=httpx.Response(
            200, json={"merged": True, "merged_at": "2026-08-02T00:00:00Z", "state": "closed"}
        )
    )
    settings = Settings(OSS_DATA_DIR=tmp_path)
    cid = "octo-example-1"
    _seed(
        settings,
        cid,
        WorkflowState.PR_OPENED.value,
        pr_url="https://github.com/octo/example/pull/7",
    )

    run_ledger_sync(settings, console=Console())

    engine = ensure_database(settings.database_path, settings.database_url)
    session_factory = build_session_factory(engine)
    with session_factory() as session:
        row = session.execute(
            select(ContributionRow).where(ContributionRow.contribution_id == cid)
        ).scalar_one()
        assert row.state == WorkflowState.MERGED.value


@pytest.mark.respx(base_url="https://api.github.com")
def test_ledger_sync_leaves_unmerged_prs_alone(
    respx_mock: respx.MockRouter, tmp_path: Path
) -> None:
    respx_mock.get("/repos/octo/example/pulls/7").mock(
        return_value=httpx.Response(200, json={"merged": False, "state": "open"})
    )
    settings = Settings(OSS_DATA_DIR=tmp_path)
    cid = "octo-example-1"
    _seed(
        settings,
        cid,
        WorkflowState.PR_OPENED.value,
        pr_url="https://github.com/octo/example/pull/7",
    )

    run_ledger_sync(settings, console=Console())

    engine = ensure_database(settings.database_path, settings.database_url)
    session_factory = build_session_factory(engine)
    with session_factory() as session:
        row = session.execute(
            select(ContributionRow).where(ContributionRow.contribution_id == cid)
        ).scalar_one()
        # advanced PR_OPENED -> REVIEW_IN_PROGRESS but not to MERGED
        assert row.state == WorkflowState.REVIEW_IN_PROGRESS.value


@pytest.mark.respx(base_url="https://api.github.com")
def test_resume_generate_after_merge_produces_bullet_and_skills(
    respx_mock: respx.MockRouter, tmp_path: Path
) -> None:
    respx_mock.get("/repos/octo/example/pulls/7").mock(
        return_value=httpx.Response(
            200, json={"merged": True, "merged_at": "2026-08-02T00:00:00Z", "state": "closed"}
        )
    )
    settings = Settings(OSS_DATA_DIR=tmp_path)
    cid = "octo-example-1"
    _seed(
        settings,
        cid,
        WorkflowState.PR_OPENED.value,
        pr_url="https://github.com/octo/example/pull/7",
    )

    console = Console()
    run_ledger_sync(settings, console=console)
    run_resume_generate(settings, cid, console=console)

    engine = ensure_database(settings.database_path, settings.database_url)
    session_factory = build_session_factory(engine)
    with session_factory() as session:
        row = session.execute(
            select(ContributionRow).where(ContributionRow.contribution_id == cid)
        ).scalar_one()
        assert row.resume_bullet is not None
        assert "octo/example" in row.resume_bullet
        assert "Python" in row.extra_json["skills_demonstrated"]
