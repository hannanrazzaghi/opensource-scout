"""Rendering and persistence for the contribution workflow: `oss issue
reproduce`, `oss contribution plan/implement/validate/status`.

A contribution's identity is derived deterministically from its repository
and issue number (``owner-repo-NNN``) so the same issue always maps to the
same row instead of accumulating duplicates. Every step here records a
:mod:`opensource_scout.workflows.state_machine` transition, so
``oss contribution status`` can always show exactly how a contribution got
to where it is.
"""

from __future__ import annotations

import asyncio
import re
from datetime import UTC, datetime
from pathlib import Path

from rich.console import Console
from sqlalchemy import select

from opensource_scout.config import Settings
from opensource_scout.db.models import ContributionRow, IssueRow, ProjectRow, WorkflowTransitionRow
from opensource_scout.db.session import build_session_factory, ensure_database
from opensource_scout.domain.context import ContextBundle
from opensource_scout.domain.enums import WorkflowState
from opensource_scout.llm.cache import SqlAlchemyLlmCache
from opensource_scout.llm.client import OpenAiClient
from opensource_scout.workflows.implementation import plan_implementation, validate_contribution
from opensource_scout.workflows.reproduction import reproduce_issue
from opensource_scout.workflows.state_machine import InvalidTransitionError, transition

_TEST_COMMAND_HINTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("pytest", ("python3", "-m", "pytest", "-q")),
    ("cargo test", ("cargo", "test")),
    ("npm test", ("npm", "test")),
    ("yarn test", ("yarn", "test")),
)


def contribution_id_for(repository: str, issue_number: int) -> str:
    return f"{repository.replace('/', '-')}-{issue_number}"


def _record_transition(
    session, contribution_id: str, from_state: WorkflowState, to_state: WorkflowState, evidence: str
) -> None:
    record = transition(contribution_id, from_state, to_state, evidence=evidence)
    session.add(
        WorkflowTransitionRow(
            contribution_id=contribution_id,
            from_state=record.from_state.value,
            to_state=record.to_state.value,
            evidence=record.evidence,
            occurred_at=record.at,
        )
    )


def _get_or_create_contribution(
    session, contribution_id: str, repository: str, issue_number: int
) -> ContributionRow:
    row = session.execute(
        select(ContributionRow).where(ContributionRow.contribution_id == contribution_id)
    ).scalar_one_or_none()
    if row is None:
        now = datetime.now(UTC)
        row = ContributionRow(
            contribution_id=contribution_id,
            repository_full_name=repository,
            issue_number=issue_number,
            state=WorkflowState.PROFILE_READY.value,
            created_at=now,
            updated_at=now,
        )
        session.add(row)
        session.flush()
    return row


def _fast_forward_to_issue_selected(session, row: ContributionRow) -> None:
    """Advance a fresh contribution through the discovery states that
    already happened via earlier `oss project select` / `oss issue select`
    commands, recording each hop rather than skipping straight to
    ISSUE_SELECTED."""
    chain = [
        WorkflowState.PROFILE_READY,
        WorkflowState.PROJECT_DISCOVERY,
        WorkflowState.PROJECT_SELECTED,
        WorkflowState.REPOSITORY_INSPECTED,
        WorkflowState.ISSUE_DISCOVERY,
        WorkflowState.ISSUE_SELECTED,
    ]
    current = WorkflowState(row.state)
    start_index = chain.index(current) if current in chain else 0
    for from_state, to_state in zip(chain[start_index:], chain[start_index + 1 :], strict=False):
        _record_transition(
            session,
            row.contribution_id,
            from_state,
            to_state,
            evidence="already completed via earlier discovery/select commands",
        )
        row.state = to_state.value
    row.updated_at = datetime.now(UTC)


def _find_test_command(project_row: ProjectRow | None) -> tuple[str, ...] | None:
    if project_row is None:
        return None
    rules = (project_row.metadata_json or {}).get("contribution_rules", [])
    excerpts = " ".join(
        r.get("excerpt", "") for r in rules if r.get("category") == "test_command"
    ).lower()
    for needle, command in _TEST_COMMAND_HINTS:
        if needle in excerpts:
            return command
    return None


def run_issue_reproduce(
    settings: Settings,
    repository: str,
    number: int,
    *,
    console: Console,
    clone_url: str | None = None,
) -> None:
    """``clone_url`` overrides the default GitHub clone URL — tests pass a
    local ``file://`` URL to avoid a real network dependency."""
    engine = ensure_database(settings.database_path, settings.database_url)
    session_factory = build_session_factory(engine)
    contribution_id = contribution_id_for(repository, number)

    with session_factory() as session:
        issue_row = session.execute(
            select(IssueRow).where(
                IssueRow.repository_full_name == repository, IssueRow.number == number
            )
        ).scalar_one_or_none()
        project_row = session.execute(
            select(ProjectRow).where(ProjectRow.full_name == repository)
        ).scalar_one_or_none()

        if issue_row is None or not issue_row.selected:
            console.print(
                f"[red]{repository}#{number} has not been selected.[/red] "
                f"Run `oss issue select {repository} {number}` first."
            )
            return

        contribution = _get_or_create_contribution(session, contribution_id, repository, number)
        try:
            _fast_forward_to_issue_selected(session, contribution)
        except InvalidTransitionError as exc:
            console.print(f"[red]cannot reproduce from current state:[/red] {exc}")
            return
        session.commit()

        test_command = _find_test_command(project_row)

    console.print(f"[cyan]Reproducing {repository}#{number} in an isolated workspace...[/cyan]")
    if test_command is None:
        console.print("[yellow]No test command found in extracted repository rules.[/yellow]")

    report = asyncio.run(
        reproduce_issue(
            settings.workspace_dir,
            contribution_id,
            repository,
            test_command=test_command,
            clone_url=clone_url,
            session_factory=session_factory,
        )
    )

    with session_factory() as session:
        contribution = session.execute(
            select(ContributionRow).where(ContributionRow.contribution_id == contribution_id)
        ).scalar_one()
        contribution.base_commit_sha = report.base_commit_sha or None
        extra = dict(contribution.extra_json or {})
        extra["reproduction_report"] = report.model_dump(mode="json")
        contribution.extra_json = extra
        _record_transition(
            session,
            contribution_id,
            WorkflowState.ISSUE_SELECTED,
            WorkflowState.ISSUE_REPRODUCED,
            evidence=f"reproduction status: {report.status.value}",
        )
        contribution.state = WorkflowState.ISSUE_REPRODUCED.value
        contribution.updated_at = datetime.now(UTC)
        session.commit()

    console.print(f"\n[bold]Status:[/bold] {report.status.value}")
    console.print(report.summary)
    for e in report.evidence:
        console.print(f"  {e}")
    console.print(f"\nContribution ID: [cyan]{contribution_id}[/cyan]")


_WORD_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")


def _read_workspace_files(workspace_path: Path, *, max_files: int = 40) -> dict[str, str]:
    files: dict[str, str] = {}
    if not workspace_path.exists():
        return files
    for path in sorted(workspace_path.rglob("*.py"))[:max_files]:
        if ".git" in path.parts:
            continue
        try:
            files[str(path.relative_to(workspace_path))] = path.read_text(
                encoding="utf-8", errors="replace"
            )
        except OSError:
            continue
    return files


def run_contribution_plan(settings: Settings, issue_id: str, *, console: Console) -> None:
    if "#" not in issue_id:
        console.print(f"[red]Expected owner/repository#number, got {issue_id!r}.[/red]")
        return
    repository, _, number_str = issue_id.rpartition("#")
    number = int(number_str)
    contribution_id = contribution_id_for(repository, number)

    engine = ensure_database(settings.database_path, settings.database_url)
    session_factory = build_session_factory(engine)

    with session_factory() as session:
        contribution = session.execute(
            select(ContributionRow).where(ContributionRow.contribution_id == contribution_id)
        ).scalar_one_or_none()
        issue_row = session.execute(
            select(IssueRow).where(
                IssueRow.repository_full_name == repository, IssueRow.number == number
            )
        ).scalar_one_or_none()
        if contribution is None or contribution.state != WorkflowState.ISSUE_REPRODUCED.value:
            console.print(
                f"[red]{issue_id} must be reproduced first.[/red] "
                f"Run `oss issue reproduce {repository} {number}`."
            )
            return

        problem = issue_row.title if issue_row else f"Issue {issue_id}"
        problem_body = (issue_row.metadata_json or {}).get("body", "") if issue_row else ""

    files = _read_workspace_files(settings.workspace_dir / contribution_id)
    query_terms = list({m.group(0) for m in _WORD_PATTERN.finditer(f"{problem} {problem_body}")})
    from opensource_scout.llm.context import build_context_bundle

    context: ContextBundle = build_context_bundle(
        contribution.base_commit_sha or "", files, query_terms
    )

    token = settings.openai_api_key_value()
    llm_client = OpenAiClient(api_key=token)
    cache = SqlAlchemyLlmCache(session_factory)
    try:
        plan = asyncio.run(
            plan_implementation(
                settings=settings,
                session_factory=session_factory,
                cache=cache,
                llm_client=llm_client,
                problem=f"{problem}\n\n{problem_body}",
                context=context,
                calls_this_workflow=0,
            )
        )
    finally:
        asyncio.run(llm_client.aclose())

    with session_factory() as session:
        contribution = session.execute(
            select(ContributionRow).where(ContributionRow.contribution_id == contribution_id)
        ).scalar_one()
        extra = dict(contribution.extra_json or {})
        extra["implementation_plan"] = plan.model_dump(mode="json")
        contribution.extra_json = extra
        _record_transition(
            session,
            contribution_id,
            WorkflowState.ISSUE_REPRODUCED,
            WorkflowState.IMPLEMENTATION_PLANNED,
            evidence="implementation plan generated",
        )
        contribution.state = WorkflowState.IMPLEMENTATION_PLANNED.value
        contribution.updated_at = datetime.now(UTC)
        session.commit()

    console.print(f"[bold]Problem:[/bold] {plan.problem}")
    console.print(f"[bold]Root cause hypothesis:[/bold] {plan.root_cause_hypothesis}")
    console.print("\n[bold]Proposed changes:[/bold]")
    for c in plan.proposed_changes:
        console.print(f"  - {c}")
    console.print("\n[bold]Tests:[/bold]")
    for t in plan.tests:
        console.print(f"  - {t}")
    console.print(f"\nEstimated hours: {plan.estimated_hours}")


def run_contribution_implement(
    settings: Settings, contribution_id: str, *, console: Console
) -> None:
    engine = ensure_database(settings.database_path, settings.database_url)
    session_factory = build_session_factory(engine)
    with session_factory() as session:
        contribution = session.execute(
            select(ContributionRow).where(ContributionRow.contribution_id == contribution_id)
        ).scalar_one_or_none()
        if contribution is None or contribution.state != WorkflowState.IMPLEMENTATION_PLANNED.value:
            console.print(
                f"[red]{contribution_id} has no approved plan to implement.[/red] "
                "Run `oss contribution plan` first."
            )
            return
        _record_transition(
            session,
            contribution_id,
            WorkflowState.IMPLEMENTATION_PLANNED,
            WorkflowState.IMPLEMENTING,
            evidence="implementation started",
        )
        contribution.state = WorkflowState.IMPLEMENTING.value
        contribution.updated_at = datetime.now(UTC)
        session.commit()

    console.print(
        f"[green]Marked {contribution_id} as IMPLEMENTING.[/green]\n"
        "OpenSourceScout does not write code to disk automatically — review the plan with "
        "`oss contribution status`, make the change in the workspace yourself, then run "
        "`oss contribution validate`."
    )


def run_contribution_validate(
    settings: Settings, contribution_id: str, *, console: Console
) -> None:
    engine = ensure_database(settings.database_path, settings.database_url)
    session_factory = build_session_factory(engine)
    with session_factory() as session:
        contribution = session.execute(
            select(ContributionRow).where(ContributionRow.contribution_id == contribution_id)
        ).scalar_one_or_none()
        if contribution is None or contribution.state != WorkflowState.IMPLEMENTING.value:
            console.print(f"[red]{contribution_id} is not in IMPLEMENTING state.[/red]")
            return
        project_row = session.execute(
            select(ProjectRow).where(ProjectRow.full_name == contribution.repository_full_name)
        ).scalar_one_or_none()
        test_command = _find_test_command(project_row)
        _record_transition(
            session,
            contribution_id,
            WorkflowState.IMPLEMENTING,
            WorkflowState.VALIDATING,
            evidence="validation started",
        )
        contribution.state = WorkflowState.VALIDATING.value
        session.commit()

    commands: dict[str, tuple[str, ...]] = {}
    if test_command:
        commands["test"] = test_command

    workspace_path = settings.workspace_dir / contribution_id
    results = asyncio.run(
        validate_contribution(
            workspace_path,
            commands,
            contribution_id=contribution_id,
            session_factory=session_factory,
        )
    )
    all_passed = bool(results) and all(r.status.value == "PASSED" for r in results)

    with session_factory() as session:
        contribution = session.execute(
            select(ContributionRow).where(ContributionRow.contribution_id == contribution_id)
        ).scalar_one()
        extra = dict(contribution.extra_json or {})
        extra["validation_results"] = [r.model_dump(mode="json") for r in results]
        contribution.extra_json = extra
        next_state = WorkflowState.PR_PREPARED if all_passed else WorkflowState.IMPLEMENTING
        _record_transition(
            session,
            contribution_id,
            WorkflowState.VALIDATING,
            next_state,
            evidence=f"all_passed={all_passed}",
        )
        contribution.state = next_state.value
        contribution.updated_at = datetime.now(UTC)
        session.commit()

    for r in results:
        console.print(f"{r.command}: [bold]{r.status.value}[/bold]")
    if not results:
        console.print("[yellow]No validation commands were available to run.[/yellow]")
    console.print(f"\nNew state: {next_state.value}")


def run_contribution_status(settings: Settings, contribution_id: str, *, console: Console) -> None:
    engine = ensure_database(settings.database_path, settings.database_url)
    session_factory = build_session_factory(engine)
    with session_factory() as session:
        contribution = session.execute(
            select(ContributionRow).where(ContributionRow.contribution_id == contribution_id)
        ).scalar_one_or_none()
        if contribution is None:
            console.print(f"[red]No contribution {contribution_id!r}.[/red]")
            return
        transitions = (
            session.execute(
                select(WorkflowTransitionRow)
                .where(WorkflowTransitionRow.contribution_id == contribution_id)
                .order_by(WorkflowTransitionRow.id)
            )
            .scalars()
            .all()
        )

        console.print(f"[bold]{contribution_id}[/bold]  ({contribution.repository_full_name})")
        console.print(f"State: [cyan]{contribution.state}[/cyan]")
        console.print("\n[bold]History:[/bold]")
        for t in transitions:
            console.print(f"  {t.from_state} -> {t.to_state}  ({t.evidence})")

        extra = contribution.extra_json or {}
        if "reproduction_report" in extra:
            console.print(f"\nReproduction: {extra['reproduction_report']['status']}")
        if "implementation_plan" in extra:
            console.print(f"Plan: {extra['implementation_plan']['problem']}")
        if "validation_results" in extra:
            statuses = [r["status"] for r in extra["validation_results"]]
            console.print(f"Validation: {statuses}")
