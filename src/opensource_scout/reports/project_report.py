"""Rendering and persistence for project discovery: `oss discover projects`,
`oss projects list`, `oss project inspect`, `oss project select`.

Kept as plain functions the CLI calls directly (see :mod:`opensource_scout.cli`)
rather than a class — there's no state here beyond what's already in the
database and the Settings object each function receives explicitly.
"""

from __future__ import annotations

import asyncio

from rich.console import Console
from rich.table import Table
from sqlalchemy import select

from opensource_scout.config import Settings
from opensource_scout.db.models import ProjectRow
from opensource_scout.db.session import build_session_factory, ensure_database
from opensource_scout.domain.models import ProjectScore, RepositoryCandidate
from opensource_scout.domain.profile import HANNAN_PROFILE
from opensource_scout.github.client import GitHubRestClient
from opensource_scout.github.discovery import discover_repository_candidates
from opensource_scout.github.graphql import GraphQLClient
from opensource_scout.scoring.project import rank_projects

TOP_N = 10


def _persist_scores(
    settings: Settings,
    scores: list[ProjectScore],
    candidates_by_name: dict[str, RepositoryCandidate],
) -> None:
    engine = ensure_database(settings.database_path, settings.database_url)
    session_factory = build_session_factory(engine)
    with session_factory() as session:
        for score in scores:
            candidate = candidates_by_name[score.repository_full_name]
            row = session.execute(
                select(ProjectRow).where(ProjectRow.full_name == score.repository_full_name)
            ).scalar_one_or_none()
            if row is None:
                row = ProjectRow(full_name=score.repository_full_name, url=candidate.url)
                session.add(row)
            row.url = candidate.url
            row.metadata_json = candidate.model_dump(mode="json")
            row.score_json = score.model_dump(mode="json")
            row.score_total = score.total
        session.commit()


def run_discover_projects(settings: Settings, *, limit: int, console: Console) -> None:
    console.print(f"[cyan]Searching GitHub across target domains (limit={limit})...[/cyan]")
    scores_and_candidates = asyncio.run(_run_discovery_with_candidates(settings, limit=limit))
    scores, candidates_by_name = scores_and_candidates

    _persist_scores(settings, scores, candidates_by_name)
    console.print(f"[green]Discovered and scored {len(scores)} candidates.[/green]\n")
    _render_top_scores(scores, console)
    _render_recommendation(scores, console)


async def _run_discovery_with_candidates(
    settings: Settings, *, limit: int
) -> tuple[list[ProjectScore], dict[str, RepositoryCandidate]]:
    token = settings.github_token_value()
    async with GitHubRestClient(
        token=token, concurrency=settings.github_concurrency
    ) as rest_client:
        graphql_client = GraphQLClient(token=token)
        try:
            candidates = await discover_repository_candidates(
                rest_client, graphql_client, min_candidates=limit
            )
        finally:
            await graphql_client.aclose()

    scores = rank_projects(candidates, HANNAN_PROFILE)
    by_name = {c.full_name: c for c in candidates}
    return scores, by_name


def _render_top_scores(scores: list[ProjectScore], console: Console) -> None:
    table = Table(title=f"Top {min(TOP_N, len(scores))} projects")
    table.add_column("Repository")
    table.add_column("Total", justify="right")
    table.add_column("Career", justify="right")
    table.add_column("Accept", justify="right")
    table.add_column("Depth", justify="right")
    table.add_column("Maintain", justify="right")
    table.add_column("Hardware", justify="right")
    table.add_column("Repeat", justify="right")

    for score in scores[:TOP_N]:
        table.add_row(
            score.repository_full_name,
            str(score.total),
            str(score.career_relevance.value),
            str(score.acceptance_probability.value),
            str(score.technical_depth.value),
            str(score.maintainer_activity.value),
            str(score.hardware_compatibility.value),
            str(score.repeat_contribution_value.value),
        )
    console.print(table)


def _render_recommendation(scores: list[ProjectScore], console: Console) -> None:
    top = scores[:TOP_N]
    if not top:
        console.print("[yellow]No candidates to recommend.[/yellow]")
        return

    anchor = top[0]
    alternatives = top[1:3]
    remaining = top[3:]
    stretch = max(remaining, key=lambda s: s.technical_depth.value, default=None)

    console.print("\n[bold]Recommendation[/bold]")
    console.print(
        f"  Anchor:       [green]{anchor.repository_full_name}[/green] (score {anchor.total})"
    )
    for alt in alternatives:
        console.print(f"  Alternative:  {alt.repository_full_name} (score {alt.total})")
    if stretch is not None:
        console.print(
            f"  Stretch:      {stretch.repository_full_name} "
            f"(score {stretch.total}, technical depth {stretch.technical_depth.value})"
        )


def run_projects_list(settings: Settings, *, console: Console) -> None:
    engine = ensure_database(settings.database_path, settings.database_url)
    session_factory = build_session_factory(engine)
    with session_factory() as session:
        rows = (
            session.execute(select(ProjectRow).order_by(ProjectRow.score_total.desc()))
            .scalars()
            .all()
        )

    if not rows:
        console.print("[yellow]No discovered projects yet. Run `oss discover projects`.[/yellow]")
        return

    table = Table(title="Discovered projects")
    table.add_column("Repository")
    table.add_column("Score", justify="right")
    table.add_column("Selected")
    for row in rows:
        table.add_row(
            row.full_name,
            str(row.score_total) if row.score_total is not None else "-",
            "yes" if row.selected else "",
        )
    console.print(table)


def run_project_inspect(settings: Settings, repository: str, *, console: Console) -> None:
    engine = ensure_database(settings.database_path, settings.database_url)
    session_factory = build_session_factory(engine)
    with session_factory() as session:
        row = session.execute(
            select(ProjectRow).where(ProjectRow.full_name == repository)
        ).scalar_one_or_none()

    if row is None:
        console.print(f"[red]No discovered project named {repository!r}.[/red]")
        console.print("Run `oss discover projects` first.")
        return

    console.print(f"[bold]{row.full_name}[/bold]  {row.url}")
    console.print(f"Score: {row.score_total}")
    score = row.score_json or {}
    for dimension in (
        "career_relevance",
        "acceptance_probability",
        "technical_depth",
        "maintainer_activity",
        "hardware_compatibility",
        "repeat_contribution_value",
    ):
        dim = score.get(dimension, {})
        console.print(f"\n[bold]{dimension}[/bold]: {dim.get('value')}/{dim.get('max_value')}")
        for e in dim.get("evidence", []):
            console.print(f"  - {e}")
    penalties = score.get("penalties", [])
    if penalties:
        console.print("\n[bold red]Penalties[/bold red]:")
        for p in penalties:
            console.print(f"  - {p}")


def run_project_select(settings: Settings, repository: str, *, console: Console) -> None:
    engine = ensure_database(settings.database_path, settings.database_url)
    session_factory = build_session_factory(engine)
    with session_factory() as session:
        row = session.execute(
            select(ProjectRow).where(ProjectRow.full_name == repository)
        ).scalar_one_or_none()
        if row is None:
            console.print(f"[red]No discovered project named {repository!r}.[/red]")
            return
        row.selected = True
        session.commit()
    console.print(f"[green]Selected[/green] {repository} as the active project.")
