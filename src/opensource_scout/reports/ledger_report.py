"""The contribution ledger: `oss ledger list/show/sync`, `oss resume generate`.

`oss ledger sync` is the only command in this module that talks to GitHub —
a read-only check of whether an open PR has been merged, used to advance a
contribution's workflow state. Résumé bullets are generated only for
contributions already in ``MERGED``/``RELEASED`` — never speculatively.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from rich.console import Console
from rich.table import Table
from sqlalchemy import select

from opensource_scout.config import Settings
from opensource_scout.db.models import ContributionRow
from opensource_scout.db.session import build_session_factory, ensure_database
from opensource_scout.domain.enums import WorkflowState
from opensource_scout.domain.profile import HANNAN_PROFILE
from opensource_scout.github.client import GitHubRestClient
from opensource_scout.github.errors import GitHubError
from opensource_scout.workflows.transitions import record_transition

_SYNCABLE_STATES = frozenset(
    {WorkflowState.PR_OPENED.value, WorkflowState.REVIEW_IN_PROGRESS.value}
)


def run_ledger_list(settings: Settings, *, console: Console) -> None:
    engine = ensure_database(settings.database_path, settings.database_url)
    session_factory = build_session_factory(engine)
    with session_factory() as session:
        rows = (
            session.execute(select(ContributionRow).order_by(ContributionRow.updated_at.desc()))
            .scalars()
            .all()
        )

    if not rows:
        console.print("[yellow]No contributions tracked yet.[/yellow]")
        return

    table = Table(title="Contribution ledger")
    table.add_column("ID")
    table.add_column("Repository")
    table.add_column("Issue", justify="right")
    table.add_column("State")
    table.add_column("PR")
    for row in rows:
        table.add_row(
            row.contribution_id,
            row.repository_full_name,
            str(row.issue_number) if row.issue_number else "-",
            row.state,
            row.pull_request_url or "-",
        )
    console.print(table)


def run_ledger_show(settings: Settings, contribution_id: str, *, console: Console) -> None:
    engine = ensure_database(settings.database_path, settings.database_url)
    session_factory = build_session_factory(engine)
    with session_factory() as session:
        row = session.execute(
            select(ContributionRow).where(ContributionRow.contribution_id == contribution_id)
        ).scalar_one_or_none()

    if row is None:
        console.print(f"[red]No contribution {contribution_id!r}.[/red]")
        return

    console.print(f"[bold]{row.contribution_id}[/bold]  ({row.repository_full_name})")
    console.print(f"State: {row.state}")
    console.print(f"Issue: #{row.issue_number}" if row.issue_number else "Issue: (none)")
    console.print(f"Branch: {row.branch_name or '(none)'}")
    console.print(f"Pull request: {row.pull_request_url or '(none)'}")
    skills = (row.extra_json or {}).get("skills_demonstrated", [])
    console.print(f"Skills demonstrated: {', '.join(skills) or '(none recorded)'}")
    console.print(
        f"Résumé bullet: {row.resume_bullet or '(not generated — contribution not merged yet)'}"
    )


async def _fetch_pr_state(
    client: GitHubRestClient, repository_full_name: str, pull_request_url: str
) -> dict | None:
    number = pull_request_url.rstrip("/").rsplit("/", 1)[-1]
    if not number.isdigit():
        return None
    try:
        return await client.get_json(f"/repos/{repository_full_name}/pulls/{number}")
    except GitHubError:
        return None


def run_ledger_sync(settings: Settings, *, console: Console) -> None:
    engine = ensure_database(settings.database_path, settings.database_url)
    session_factory = build_session_factory(engine)

    with session_factory() as session:
        rows = (
            session.execute(
                select(ContributionRow).where(ContributionRow.state.in_(_SYNCABLE_STATES))
            )
            .scalars()
            .all()
        )
        targets = [
            (r.contribution_id, r.repository_full_name, r.pull_request_url)
            for r in rows
            if r.pull_request_url
        ]

    if not targets:
        console.print("[yellow]No open pull requests to sync.[/yellow]")
        return

    async def _sync_all() -> dict[str, dict | None]:
        client = GitHubRestClient(token=settings.github_token_value())
        try:
            results = {}
            for cid, repo, url in targets:
                results[cid] = await _fetch_pr_state(client, repo, url)
            return results
        finally:
            await client.aclose()

    pr_states = asyncio.run(_sync_all())

    with session_factory() as session:
        for cid, _repo, _url in targets:
            pr_data = pr_states.get(cid)
            if pr_data is None:
                console.print(f"{cid}: could not fetch PR status")
                continue

            row = session.execute(
                select(ContributionRow).where(ContributionRow.contribution_id == cid)
            ).scalar_one()

            if row.state == WorkflowState.PR_OPENED.value:
                record_transition(
                    session,
                    cid,
                    WorkflowState.PR_OPENED,
                    WorkflowState.REVIEW_IN_PROGRESS,
                    evidence="synced from GitHub",
                )
                row.state = WorkflowState.REVIEW_IN_PROGRESS.value

            if pr_data.get("merged"):
                record_transition(
                    session,
                    cid,
                    WorkflowState.REVIEW_IN_PROGRESS,
                    WorkflowState.MERGED,
                    evidence=f"PR merged at {pr_data.get('merged_at')}",
                )
                row.state = WorkflowState.MERGED.value
                console.print(f"{cid}: [green]MERGED[/green]")
            else:
                console.print(f"{cid}: still {pr_data.get('state', 'open')}")

            row.updated_at = datetime.now(UTC)
        session.commit()


def run_resume_generate(settings: Settings, contribution_id: str, *, console: Console) -> None:
    engine = ensure_database(settings.database_path, settings.database_url)
    session_factory = build_session_factory(engine)
    with session_factory() as session:
        row = session.execute(
            select(ContributionRow).where(ContributionRow.contribution_id == contribution_id)
        ).scalar_one_or_none()
        if row is None:
            console.print(f"[red]No contribution {contribution_id!r}.[/red]")
            return
        if row.state not in (WorkflowState.MERGED.value, WorkflowState.RELEASED.value):
            console.print(
                f"[red]Cannot generate a résumé bullet for {contribution_id}: "
                f"state is {row.state}, not MERGED/RELEASED.[/red] Run `oss ledger sync` first."
            )
            return

        plan = (row.extra_json or {}).get("implementation_plan") or {}
        problem = plan.get("problem", "a bug")
        bullet = (
            f"Diagnosed and fixed {problem} in {row.repository_full_name} "
            f"(#{row.issue_number}), merged via {row.pull_request_url}."
        )
        row.resume_bullet = bullet

        text = f"{problem} {plan.get('root_cause_hypothesis', '')}".lower()
        skills = [s for s in HANNAN_PROFILE.skills if s.lower() in text]
        extra = dict(row.extra_json or {})
        extra["skills_demonstrated"] = skills
        row.extra_json = extra
        session.commit()

    console.print(f"[green]Résumé bullet generated:[/green]\n{bullet}")
