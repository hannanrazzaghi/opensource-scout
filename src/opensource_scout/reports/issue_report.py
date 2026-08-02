"""Rendering and persistence for issue discovery: `oss discover issues`,
`oss issues list`, `oss issue inspect`, `oss issue select`.

Mirrors :mod:`opensource_scout.reports.project_report`'s structure.
"""

from __future__ import annotations

import asyncio

from rich.console import Console
from rich.table import Table
from sqlalchemy import select

from opensource_scout.config import Settings
from opensource_scout.db.models import IssueRow, ProjectRow
from opensource_scout.db.session import build_session_factory, ensure_database
from opensource_scout.domain.models import ContributionRule, IssueCandidate, IssueScore
from opensource_scout.domain.profile import HANNAN_PROFILE
from opensource_scout.github.client import GitHubRestClient
from opensource_scout.github.graphql import GraphQLClient
from opensource_scout.github.issues import discover_issues
from opensource_scout.repository.rules import extract_contribution_rules
from opensource_scout.scoring.issue import rank_issues

TOP_N = 5


async def _run_discovery(
    settings: Settings, owner: str, name: str
) -> tuple[list[IssueScore], dict[str, IssueCandidate], list[ContributionRule]]:
    token = settings.github_token_value()
    async with GitHubRestClient(
        token=token, concurrency=settings.github_concurrency
    ) as rest_client:
        graphql_client = GraphQLClient(token=token)
        try:
            candidates = await discover_issues(rest_client, graphql_client, owner, name)
            rules = await extract_contribution_rules(rest_client, owner, name)
        finally:
            await graphql_client.aclose()

    scores = rank_issues(candidates, HANNAN_PROFILE)
    candidates_by_key = {f"{c.repository_full_name}#{c.number}": c for c in candidates}
    return scores, candidates_by_key, rules


def _persist(
    settings: Settings,
    repository_full_name: str,
    scores: list[IssueScore],
    candidates_by_key: dict[str, IssueCandidate],
    rules: list[ContributionRule],
) -> None:
    engine = ensure_database(settings.database_path, settings.database_url)
    session_factory = build_session_factory(engine)
    with session_factory() as session:
        for score in scores:
            candidate = candidates_by_key[score.issue_key]
            row = session.execute(
                select(IssueRow).where(
                    IssueRow.repository_full_name == repository_full_name,
                    IssueRow.number == candidate.number,
                )
            ).scalar_one_or_none()
            if row is None:
                row = IssueRow(
                    repository_full_name=repository_full_name,
                    number=candidate.number,
                    title=candidate.title,
                    url=candidate.url,
                )
                session.add(row)
            row.title = candidate.title
            row.url = candidate.url
            row.metadata_json = candidate.model_dump(mode="json")
            row.score_json = score.model_dump(mode="json")
            row.score_total = score.total
            row.rejected = score.rejected

        project_row = session.execute(
            select(ProjectRow).where(ProjectRow.full_name == repository_full_name)
        ).scalar_one_or_none()
        if project_row is not None and rules:
            metadata = dict(project_row.metadata_json or {})
            metadata["contribution_rules"] = [r.model_dump(mode="json") for r in rules]
            project_row.metadata_json = metadata

        session.commit()


def run_discover_issues(settings: Settings, repository: str, *, console: Console) -> None:
    if "/" not in repository:
        console.print(f"[red]Expected owner/repository, got {repository!r}.[/red]")
        return
    owner, name = repository.split("/", 1)

    console.print(f"[cyan]Discovering issues for {repository}...[/cyan]")
    scores, candidates_by_key, rules = asyncio.run(_run_discovery(settings, owner, name))

    if not scores:
        console.print("[yellow]No open issues found.[/yellow]")
        return

    _persist(settings, repository, scores, candidates_by_key, rules)

    console.print(f"[green]Discovered and scored {len(scores)} issues.[/green]")
    if rules:
        console.print(f"Extracted {len(rules)} contribution rules from repository files.\n")
    _render_top_scores(scores, candidates_by_key, console)
    _render_recommendation(scores, console)


def _render_top_scores(
    scores: list[IssueScore], candidates_by_key: dict[str, IssueCandidate], console: Console
) -> None:
    eligible = [s for s in scores if not s.rejected][:TOP_N]
    table = Table(title=f"Top {len(eligible)} eligible issues")
    table.add_column("#", justify="right")
    table.add_column("Title")
    table.add_column("Total", justify="right")
    table.add_column("Career", justify="right")
    table.add_column("Clarity", justify="right")
    table.add_column("Accept", justify="right")
    table.add_column("Value", justify="right")
    table.add_column("Testable", justify="right")
    table.add_column("Fit", justify="right")

    for score in eligible:
        candidate = candidates_by_key[score.issue_key]
        table.add_row(
            str(candidate.number),
            candidate.title[:50],
            str(score.total),
            str(score.career_relevance.value),
            str(score.scope_clarity.value),
            str(score.acceptance_probability.value),
            str(score.technical_value.value),
            str(score.testability.value),
            str(score.schedule_fit.value),
        )
    console.print(table)

    rejected_count = sum(1 for s in scores if s.rejected)
    if rejected_count:
        console.print(
            f"[dim]{rejected_count} issue(s) rejected — see `oss issue inspect` for why.[/dim]"
        )


def _render_recommendation(scores: list[IssueScore], console: Console) -> None:
    eligible = [s for s in scores if not s.rejected]
    if not eligible:
        console.print("\n[yellow]No eligible issues to recommend.[/yellow]")
        return
    primary, *rest = eligible[:3]
    console.print("\n[bold]Recommendation[/bold]")
    console.print(f"  Primary: [green]{primary.issue_key}[/green] (score {primary.total})")
    for backup in rest:
        console.print(f"  Backup:  {backup.issue_key} (score {backup.total})")


def run_issues_list(settings: Settings, *, console: Console) -> None:
    engine = ensure_database(settings.database_path, settings.database_url)
    session_factory = build_session_factory(engine)
    with session_factory() as session:
        rows = (
            session.execute(select(IssueRow).order_by(IssueRow.score_total.desc())).scalars().all()
        )

    if not rows:
        console.print(
            "[yellow]No discovered issues yet. Run `oss discover issues <owner/repo>`.[/yellow]"
        )
        return

    table = Table(title="Discovered issues")
    table.add_column("Repository")
    table.add_column("#", justify="right")
    table.add_column("Title")
    table.add_column("Score", justify="right")
    table.add_column("Rejected")
    for row in rows:
        table.add_row(
            row.repository_full_name,
            str(row.number),
            row.title[:60],
            str(row.score_total) if row.score_total is not None else "-",
            "yes" if row.rejected else "",
        )
    console.print(table)


def run_issue_inspect(
    settings: Settings, repository: str, number: int, *, console: Console
) -> None:
    engine = ensure_database(settings.database_path, settings.database_url)
    session_factory = build_session_factory(engine)
    with session_factory() as session:
        row = session.execute(
            select(IssueRow).where(
                IssueRow.repository_full_name == repository, IssueRow.number == number
            )
        ).scalar_one_or_none()

    if row is None:
        console.print(f"[red]No discovered issue {repository}#{number}.[/red]")
        console.print("Run `oss discover issues <owner/repo>` first.")
        return

    console.print(f"[bold]{row.repository_full_name}#{row.number}[/bold]  {row.title}")
    console.print(row.url)
    console.print(f"Score: {row.score_total}  Rejected: {row.rejected}")
    score = row.score_json or {}
    if score.get("rejection_reasons"):
        console.print("\n[bold red]Rejection reasons[/bold red]:")
        for r in score["rejection_reasons"]:
            console.print(f"  - {r}")

    for dimension in (
        "career_relevance",
        "scope_clarity",
        "acceptance_probability",
        "technical_value",
        "testability",
        "schedule_fit",
    ):
        dim = score.get(dimension, {})
        console.print(f"\n[bold]{dimension}[/bold]: {dim.get('value')}/{dim.get('max_value')}")
        for e in dim.get("evidence", []):
            console.print(f"  - {e}")


def run_issue_select(settings: Settings, repository: str, number: int, *, console: Console) -> None:
    engine = ensure_database(settings.database_path, settings.database_url)
    session_factory = build_session_factory(engine)
    with session_factory() as session:
        row = session.execute(
            select(IssueRow).where(
                IssueRow.repository_full_name == repository, IssueRow.number == number
            )
        ).scalar_one_or_none()
        if row is None:
            console.print(f"[red]No discovered issue {repository}#{number}.[/red]")
            return
        if row.rejected:
            console.print(
                f"[yellow]Warning:[/yellow] {repository}#{number} was flagged for rejection; "
                "selecting it anyway."
            )
        row.selected = True
        session.commit()
    console.print(f"[green]Selected[/green] {repository}#{number} as the active issue.")
