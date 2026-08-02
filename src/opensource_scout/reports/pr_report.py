"""PR preparation and approval-gated GitHub mutation commands.

Two workflow steps require a human approval, requested and consumed
independently: pushing a branch (`oss github push`) and opening a pull
request (`oss github open-pr`). Neither ever runs without a valid,
unexpired, single-use `Approval` of the matching kind — enforced by
:mod:`opensource_scout.workflows.state_machine`, not just this module's own
checks.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from rich.console import Console
from sqlalchemy import select

from opensource_scout.approvals.service import (
    ApprovalError,
    consume_approval,
    find_valid_approval,
    request_approval,
)
from opensource_scout.config import Settings
from opensource_scout.db.models import ContributionRow
from opensource_scout.db.session import build_session_factory, ensure_database
from opensource_scout.domain.enums import ApprovalKind, WorkflowState
from opensource_scout.execution.command import CommandSpec, RiskClassification, run_command
from opensource_scout.github.client import GitHubRestClient
from opensource_scout.workflows.state_machine import ApprovalRequiredError, InvalidTransitionError
from opensource_scout.workflows.transitions import record_transition


def _pr_body(plan: dict, validation_results: list[dict]) -> str:
    tested = "\n".join(f"- {r['command']}: {r['status']}" for r in validation_results) or (
        "- (no automated validation was recorded)"
    )
    return (
        f"## What was wrong\n{plan['problem']}\n\n"
        f"## Why it mattered\n{plan['root_cause_hypothesis']}\n\n"
        f"## How it was fixed\n" + "\n".join(f"- {c}" for c in plan["proposed_changes"]) + "\n\n"
        f"## How it was tested\n{tested}\n\n"
        f"## What was intentionally not changed\n"
        "- Everything outside the scope of this fix; no unrelated refactoring or cleanup.\n"
    )


def run_pr_prepare(settings: Settings, contribution_id: str, *, console: Console) -> None:
    engine = ensure_database(settings.database_path, settings.database_url)
    session_factory = build_session_factory(engine)

    with session_factory() as session:
        contribution = session.execute(
            select(ContributionRow).where(ContributionRow.contribution_id == contribution_id)
        ).scalar_one_or_none()
        if contribution is None or contribution.state != WorkflowState.PR_PREPARED.value:
            console.print(
                f"[red]{contribution_id} is not ready for PR preparation.[/red] "
                "It must have passed `oss contribution validate` first."
            )
            return

        plan = (contribution.extra_json or {}).get("implementation_plan")
        if plan is None:
            console.print(f"[red]{contribution_id} has no implementation plan recorded.[/red]")
            return
        validation_results = (contribution.extra_json or {}).get("validation_results", [])

        branch_name = f"oss/{contribution.issue_number}-{plan['problem'][:40]}".replace(
            " ", "-"
        ).lower()
        pr_title = f"fix: {plan['problem']}"[:72]
        pr_body = _pr_body(plan, validation_results)
        commit_message = f"fix: {plan['problem']}\n\n{plan['root_cause_hypothesis']}"
        if contribution.issue_number:
            pr_body += f"\nCloses #{contribution.issue_number}\n"

        pr_prep = {
            "branch_name": branch_name,
            "commit_message": commit_message,
            "pr_title": pr_title,
            "pr_body": pr_body,
            "compliance_checklist": [
                "Follows the repository's existing formatting/lint configuration",
                "Includes regression tests for the change",
                "Does not include unrelated refactoring",
            ],
        }
        extra = dict(contribution.extra_json or {})
        extra["pr_prep"] = pr_prep
        contribution.extra_json = extra

        approval_id = request_approval(session, contribution_id, ApprovalKind.PUSH_EXTERNAL_BRANCH)
        record_transition(
            session,
            contribution_id,
            WorkflowState.PR_PREPARED,
            WorkflowState.AWAITING_PUSH_APPROVAL,
            evidence=f"PR materials prepared; approval {approval_id} requested",
        )
        contribution.state = WorkflowState.AWAITING_PUSH_APPROVAL.value
        contribution.updated_at = datetime.now(UTC)
        session.commit()

    console.print(f"Branch: [cyan]{pr_prep['branch_name']}[/cyan]")
    console.print(f"Title: {pr_prep['pr_title']}")
    console.print(f"\n{pr_prep['pr_body']}")
    console.print(
        f"\n[bold yellow]HUMAN APPROVAL REQUIRED: PUSH EXTERNAL BRANCH[/bold yellow] "
        f"— run `oss approve {approval_id}` to authorize, then `oss github push {contribution_id}`."
    )


def run_github_push(
    settings: Settings, contribution_id: str, *, dry_run: bool, console: Console
) -> None:
    engine = ensure_database(settings.database_path, settings.database_url)
    session_factory = build_session_factory(engine)

    with session_factory() as session:
        contribution = session.execute(
            select(ContributionRow).where(ContributionRow.contribution_id == contribution_id)
        ).scalar_one_or_none()
        if contribution is None or contribution.state != WorkflowState.AWAITING_PUSH_APPROVAL.value:
            console.print(f"[red]{contribution_id} is not awaiting push approval.[/red]")
            return

        pr_prep = (contribution.extra_json or {}).get("pr_prep")
        if pr_prep is None:
            console.print(f"[red]{contribution_id} has no PR preparation recorded.[/red]")
            return

        if dry_run:
            console.print(
                f"[cyan]--dry-run:[/cyan] would push branch {pr_prep['branch_name']!r} "
                f"to {contribution.repository_full_name} after consuming a valid approval."
            )
            return

        approval = find_valid_approval(session, contribution_id, ApprovalKind.PUSH_EXTERNAL_BRANCH)
        if approval is None:
            console.print(
                f"[red]No valid approval to push a branch for {contribution_id}.[/red] "
                "Run `oss approve <approval-id>` first."
            )
            return

        workspace_path = settings.workspace_dir / contribution_id

    result = asyncio.run(
        run_command(
            CommandSpec(
                executable="git",
                args=("push", "origin", f"HEAD:{pr_prep['branch_name']}"),
                working_directory=workspace_path,
                network_required=True,
                risk=RiskClassification.EXTERNAL,
                contribution_id=contribution_id,
            ),
            session_factory=session_factory,
        )
    )

    with session_factory() as session:
        contribution = session.execute(
            select(ContributionRow).where(ContributionRow.contribution_id == contribution_id)
        ).scalar_one()
        if result.exit_code != 0:
            console.print(f"[red]git push failed:[/red]\n{result.stderr}")
            return

        try:
            consume_approval(session, approval.approval_id)
            record_transition(
                session,
                contribution_id,
                WorkflowState.AWAITING_PUSH_APPROVAL,
                WorkflowState.BRANCH_PUSHED,
                evidence=f"pushed via approval {approval.approval_id}",
                approval=approval,
            )
        except (ApprovalError, ApprovalRequiredError, InvalidTransitionError) as exc:
            console.print(f"[red]{exc}[/red]")
            return
        contribution.branch_name = pr_prep["branch_name"]
        contribution.state = WorkflowState.BRANCH_PUSHED.value
        contribution.updated_at = datetime.now(UTC)
        session.commit()

    console.print(f"[green]Pushed[/green] branch {pr_prep['branch_name']}.")


def run_github_open_pr(
    settings: Settings, contribution_id: str, *, dry_run: bool, console: Console
) -> None:
    engine = ensure_database(settings.database_path, settings.database_url)
    session_factory = build_session_factory(engine)

    with session_factory() as session:
        contribution = session.execute(
            select(ContributionRow).where(ContributionRow.contribution_id == contribution_id)
        ).scalar_one_or_none()
        if contribution is None:
            console.print(f"[red]No contribution {contribution_id!r}.[/red]")
            return

        if contribution.state == WorkflowState.BRANCH_PUSHED.value:
            approval_id = request_approval(
                session, contribution_id, ApprovalKind.OPEN_EXTERNAL_PULL_REQUEST
            )
            record_transition(
                session,
                contribution_id,
                WorkflowState.BRANCH_PUSHED,
                WorkflowState.AWAITING_PR_APPROVAL,
                evidence=f"approval {approval_id} requested",
            )
            contribution.state = WorkflowState.AWAITING_PR_APPROVAL.value
            contribution.updated_at = datetime.now(UTC)
            session.commit()
            console.print(
                f"[bold yellow]HUMAN APPROVAL REQUIRED: OPEN EXTERNAL PULL REQUEST[/bold yellow] "
                f"— run `oss approve {approval_id}` to authorize, then re-run this command."
            )
            return

        if contribution.state != WorkflowState.AWAITING_PR_APPROVAL.value:
            console.print(f"[red]{contribution_id} is not awaiting PR approval.[/red]")
            return

        pr_prep = (contribution.extra_json or {}).get("pr_prep")
        if pr_prep is None or not contribution.branch_name:
            console.print(f"[red]{contribution_id} has no prepared branch to open a PR for.[/red]")
            return

        if dry_run:
            console.print(
                f"[cyan]--dry-run:[/cyan] would open a PR titled {pr_prep['pr_title']!r} "
                f"from {contribution.branch_name} against {contribution.repository_full_name}."
            )
            return

        approval = find_valid_approval(
            session, contribution_id, ApprovalKind.OPEN_EXTERNAL_PULL_REQUEST
        )
        if approval is None:
            console.print(
                f"[red]No valid approval to open a PR for {contribution_id}.[/red] "
                "Run `oss approve <approval-id>` first."
            )
            return

        owner, name = contribution.repository_full_name.split("/", 1)
        branch_name = contribution.branch_name
        token = settings.github_token_value()

    async def _open_pr() -> dict:
        client = GitHubRestClient(token=token)
        try:
            return await client.post_json(
                f"/repos/{owner}/{name}/pulls",
                json_body={
                    "title": pr_prep["pr_title"],
                    "body": pr_prep["pr_body"],
                    "head": branch_name,
                    "base": "main",
                },
            )
        finally:
            await client.aclose()

    try:
        pr_response = asyncio.run(_open_pr())
    except Exception as exc:  # noqa: BLE001 - surfaced to the user, not swallowed
        console.print(f"[red]Failed to open pull request:[/red] {exc}")
        return

    with session_factory() as session:
        contribution = session.execute(
            select(ContributionRow).where(ContributionRow.contribution_id == contribution_id)
        ).scalar_one()
        try:
            consume_approval(session, approval.approval_id)
            pr_url = pr_response.get("html_url")
            record_transition(
                session,
                contribution_id,
                WorkflowState.AWAITING_PR_APPROVAL,
                WorkflowState.PR_OPENED,
                evidence=f"opened via approval {approval.approval_id}: {pr_url}",
                approval=approval,
            )
        except (ApprovalError, ApprovalRequiredError, InvalidTransitionError) as exc:
            console.print(f"[red]{exc}[/red]")
            return
        extra = dict(contribution.extra_json or {})
        extra["pr_response"] = pr_response
        contribution.extra_json = extra
        contribution.pull_request_url = pr_response.get("html_url")
        contribution.state = WorkflowState.PR_OPENED.value
        contribution.updated_at = datetime.now(UTC)
        session.commit()

    console.print(f"[green]Opened[/green] pull request: {pr_response.get('html_url')}")
