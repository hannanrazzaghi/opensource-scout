"""The ``oss`` command-line interface.

Every command described in the project's product spec is registered here so
``oss --help`` always reflects the full intended surface, even before a
command's implementation lands. Commands not yet implemented exit non-zero
with a clear "not implemented (phase N)" message rather than silently doing
nothing or pretending to succeed.
"""

from __future__ import annotations

import sys
from typing import Annotated

import typer
from pydantic import ValidationError
from rich.console import Console
from rich.table import Table

from opensource_scout.config import Settings, load_settings
from opensource_scout.db.session import ensure_database
from opensource_scout.domain.profile import HANNAN_PROFILE
from opensource_scout.logging import configure_logging

console = Console()
err_console = Console(stderr=True)

app = typer.Typer(
    name="oss",
    help="OpenSourceScout: discover, evaluate, and complete high-quality open-source contributions",
    no_args_is_help=True,
)


def _not_implemented(command: str, phase: str) -> typer.Exit:
    err_console.print(f"[bold red]not implemented yet:[/bold red] `{command}` lands in {phase}.")
    return typer.Exit(code=1)


def _load_settings_or_exit() -> Settings:
    try:
        return load_settings()
    except ValidationError as exc:
        err_console.print(f"[bold red]invalid configuration:[/bold red] {exc}")
        raise typer.Exit(code=1) from exc


@app.command()
def init() -> None:
    """Initialize local storage: config directories and the SQLite database."""
    settings = _load_settings_or_exit()
    settings.ensure_directories()
    configure_logging(settings.log_level, json_output=settings.log_json)
    ensure_database(settings.database_path, settings.database_url)
    console.print(f"[green]Initialized[/green] OpenSourceScout at [cyan]{settings.data_dir}[/cyan]")
    console.print(f"Database: [cyan]{settings.database_path}[/cyan]")


@app.command()
def doctor() -> None:
    """Check environment health: configuration validity, database reachability,
    and presence of required credentials for each subsystem."""
    settings = _load_settings_or_exit()

    table = Table(title="OpenSourceScout doctor")
    table.add_column("Check")
    table.add_column("Status")
    table.add_column("Detail")

    table.add_row("Configuration", "[green]OK[/green]", "loaded and validated")

    db_ok = settings.database_path.exists()
    table.add_row(
        "Database",
        "[green]OK[/green]" if db_ok else "[yellow]MISSING[/yellow]",
        str(settings.database_path) if db_ok else "run `oss init` to create it",
    )

    gh_ok = settings.github_token_value() is not None
    table.add_row(
        "GitHub token",
        "[green]configured[/green]" if gh_ok else "[yellow]not set[/yellow]",
        "GITHUB_TOKEN" if not gh_ok else "present (value hidden)",
    )

    oa_ok = settings.openai_api_key_value() is not None
    table.add_row(
        "OpenAI API key",
        "[green]configured[/green]" if oa_ok else "[yellow]not set[/yellow]",
        "OPENAI_API_KEY" if not oa_ok else "present (value hidden)",
    )

    console.print(table)
    if not db_ok:
        raise typer.Exit(code=1)


config_app = typer.Typer(help="Inspect resolved configuration.")
app.add_typer(config_app, name="config")


@config_app.command("show")
def config_show() -> None:
    """Print resolved, non-secret configuration values."""
    settings = _load_settings_or_exit()
    table = Table(title="Configuration")
    table.add_column("Key")
    table.add_column("Value")

    table.add_row("data_dir", str(settings.data_dir))
    table.add_row("workspace_dir", str(settings.workspace_dir))
    table.add_row("database_path", str(settings.database_path))
    table.add_row("github_concurrency", str(settings.github_concurrency))
    table.add_row("openai_model_fast", settings.openai_model_fast)
    table.add_row("openai_model_reasoning", settings.openai_model_reasoning)
    table.add_row("openai_model_coding", settings.openai_model_coding)
    table.add_row("daily_openai_budget_usd", str(settings.daily_openai_budget_usd))
    table.add_row("monthly_openai_budget_usd", str(settings.monthly_openai_budget_usd))
    table.add_row("max_llm_calls_per_workflow", str(settings.max_llm_calls_per_workflow))
    table.add_row("github_token", "set" if settings.github_token else "not set")
    table.add_row("openai_api_key", "set" if settings.openai_api_key else "not set")

    console.print(table)


profile_app = typer.Typer(help="Inspect the developer profile OpenSourceScout scores against.")
app.add_typer(profile_app, name="profile")


@profile_app.command("show")
def profile_show() -> None:
    """Print the developer profile used for career-relevance and hardware-
    compatibility scoring."""
    p = HANNAN_PROFILE
    console.print(f"[bold]{p.name}[/bold] ([cyan]{p.github_username}[/cyan])")
    console.print(f"{p.github_url}")
    console.print(f"OS: {p.operating_system}  Hardware: {p.hardware}")
    console.print(f"Weekly availability: {p.weekly_hours_min}-{p.weekly_hours_max}h")
    console.print(f"Objective: {p.primary_objective}\n")
    console.print(f"[bold]Skills[/bold] ({len(p.skills)}): " + ", ".join(p.skills))
    console.print(f"\n[bold]Interests[/bold] ({len(p.interests)}): " + ", ".join(p.interests))
    console.print("\n[bold]Hardware constraints[/bold]:")
    for c in p.hardware_constraints:
        console.print(f"  - {c}")


# --- Discovery ---

discover_app = typer.Typer(help="Discover projects or issues.")
app.add_typer(discover_app, name="discover")


@discover_app.command("projects")
def discover_projects(
    limit: Annotated[int, typer.Option(help="Minimum candidates to collect before ranking.")] = 30,
) -> None:
    """Search GitHub for candidate repositories and score them deterministically."""
    from opensource_scout.reports.project_report import run_discover_projects

    run_discover_projects(_load_settings_or_exit(), limit=limit, console=console)


@discover_app.command("issues")
def discover_issues(repository: str) -> None:
    """Search a selected repository for suitable issues."""
    from opensource_scout.reports.issue_report import run_discover_issues

    run_discover_issues(_load_settings_or_exit(), repository, console=console)


projects_app = typer.Typer(help="Work with discovered projects.")
app.add_typer(projects_app, name="projects")


@projects_app.command("list")
def projects_list() -> None:
    """List discovered projects with their deterministic scores."""
    from opensource_scout.reports.project_report import run_projects_list

    run_projects_list(_load_settings_or_exit(), console=console)


@app.command("project")
def project_group(
    action: Annotated[str, typer.Argument(help="inspect|select")],
    repository: str,
) -> None:
    """`oss project inspect <owner/repository>` or `oss project select <owner/repository>`."""
    from opensource_scout.reports.project_report import run_project_inspect, run_project_select

    if action not in {"inspect", "select"}:
        err_console.print(
            f"[bold red]unknown action:[/bold red] {action!r} (expected inspect|select)"
        )
        raise typer.Exit(code=2)

    settings = _load_settings_or_exit()
    if action == "inspect":
        run_project_inspect(settings, repository, console=console)
    else:
        run_project_select(settings, repository, console=console)


@app.command("issue")
def issue_group(
    action: Annotated[str, typer.Argument(help="inspect|select|reproduce")],
    repository: str,
    number: int,
) -> None:
    """`oss issue inspect|select|reproduce <owner/repository> <number>`."""
    if action not in {"inspect", "select", "reproduce"}:
        err_console.print(
            f"[bold red]unknown action:[/bold red] {action!r} (expected inspect|select|reproduce)"
        )
        raise typer.Exit(code=2)

    settings = _load_settings_or_exit()
    if action == "reproduce":
        from opensource_scout.reports.contribution_report import run_issue_reproduce

        run_issue_reproduce(settings, repository, number, console=console)
        return

    from opensource_scout.reports.issue_report import run_issue_inspect, run_issue_select

    if action == "inspect":
        run_issue_inspect(settings, repository, number, console=console)
    else:
        run_issue_select(settings, repository, number, console=console)


issues_app = typer.Typer(help="Work with discovered issues.")
app.add_typer(issues_app, name="issues")


@issues_app.command("list")
def issues_list() -> None:
    """List discovered issues with their deterministic scores."""
    from opensource_scout.reports.issue_report import run_issues_list

    run_issues_list(_load_settings_or_exit(), console=console)


# --- Contribution workflow ---

contribution_app = typer.Typer(help="Plan, implement, and validate a contribution.")
app.add_typer(contribution_app, name="contribution")


@contribution_app.command("plan")
def contribution_plan(issue_id: str) -> None:
    """`oss contribution plan <owner/repository>#<number>`."""
    from opensource_scout.reports.contribution_report import run_contribution_plan

    run_contribution_plan(_load_settings_or_exit(), issue_id, console=console)


@contribution_app.command("implement")
def contribution_implement(contribution_id: str) -> None:
    from opensource_scout.reports.contribution_report import run_contribution_implement

    run_contribution_implement(_load_settings_or_exit(), contribution_id, console=console)


@contribution_app.command("validate")
def contribution_validate(contribution_id: str) -> None:
    from opensource_scout.reports.contribution_report import run_contribution_validate

    run_contribution_validate(_load_settings_or_exit(), contribution_id, console=console)


@contribution_app.command("status")
def contribution_status(contribution_id: str) -> None:
    from opensource_scout.reports.contribution_report import run_contribution_status

    run_contribution_status(_load_settings_or_exit(), contribution_id, console=console)


# --- Claude review bridge ---

claude_app = typer.Typer(help="Export review packets for Claude Pro, and import its feedback.")
app.add_typer(claude_app, name="claude")


@claude_app.command("export")
def claude_export(review_type: str, id: Annotated[str, typer.Argument()] = "") -> None:  # noqa: A002
    raise _not_implemented("claude export", "Phase 6 (Claude review bridge)")


@claude_app.command("import")
def claude_import(review_file: str) -> None:
    raise _not_implemented("claude import", "Phase 6 (Claude review bridge)")


# --- PR preparation and GitHub mutation ---

pr_app = typer.Typer(help="Prepare pull request material.")
app.add_typer(pr_app, name="pr")


@pr_app.command("prepare")
def pr_prepare(contribution_id: str) -> None:
    raise _not_implemented("pr prepare", "Phase 6 (PR preparation)")


@app.command()
def approve(approval_id: str) -> None:
    """Grant a pending human approval for an external-repository action."""
    raise _not_implemented("approve", "Phase 6 (approval system)")


github_app = typer.Typer(help="Approval-gated GitHub mutation commands for external repositories.")
app.add_typer(github_app, name="github")


@github_app.command("push")
def github_push(
    contribution_id: str,
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
) -> None:
    raise _not_implemented("github push", "Phase 6 (GitHub mutation commands)")


@github_app.command("open-pr")
def github_open_pr(
    contribution_id: str,
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
) -> None:
    raise _not_implemented("github open-pr", "Phase 6 (GitHub mutation commands)")


# --- Ledger and résumé ---

ledger_app = typer.Typer(help="Track contributions across their lifecycle.")
app.add_typer(ledger_app, name="ledger")


@ledger_app.command("list")
def ledger_list() -> None:
    raise _not_implemented("ledger list", "Phase 6 (contribution ledger)")


@ledger_app.command("show")
def ledger_show(contribution_id: str) -> None:
    raise _not_implemented("ledger show", "Phase 6 (contribution ledger)")


resume_app = typer.Typer(help="Generate verified résumé material from merged contributions.")
app.add_typer(resume_app, name="resume")


@resume_app.command("generate")
def resume_generate(contribution_id: str) -> None:
    raise _not_implemented("resume generate", "Phase 6 (résumé generation)")


# --- Cost tracking ---

cost_app = typer.Typer(help="Inspect OpenAI spend against configured budgets.")
app.add_typer(cost_app, name="cost")


@cost_app.command("today")
def cost_today() -> None:
    """Show today's OpenAI spend against the configured daily budget."""
    from opensource_scout.db.session import build_session_factory, ensure_database
    from opensource_scout.llm.budget import spend_today

    settings = _load_settings_or_exit()
    engine = ensure_database(settings.database_path, settings.database_url)
    with build_session_factory(engine)() as session:
        spend = spend_today(session)
    console.print(f"Calls today: {spend.calls}")
    console.print(
        f"Spend today: ${spend.cost_usd:.4f} / ${settings.daily_openai_budget_usd:.2f} budget"
    )


@cost_app.command("month")
def cost_month() -> None:
    """Show this month's OpenAI spend against the configured monthly budget."""
    from opensource_scout.db.session import build_session_factory, ensure_database
    from opensource_scout.llm.budget import spend_this_month

    settings = _load_settings_or_exit()
    engine = ensure_database(settings.database_path, settings.database_url)
    with build_session_factory(engine)() as session:
        spend = spend_this_month(session)
    console.print(f"Calls this month: {spend.calls}")
    budget_usd = settings.monthly_openai_budget_usd
    console.print(f"Spend this month: ${spend.cost_usd:.4f} / ${budget_usd:.2f} budget")


def main() -> None:  # pragma: no cover - thin wrapper around typer's own entry
    app()


if __name__ == "__main__":  # pragma: no cover
    sys.exit(app())
