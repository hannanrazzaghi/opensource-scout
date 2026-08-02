"""Issue reproduction: clone the repository, run the smallest relevant
test, and report an evidenced status — never ``CONFIRMED`` without a
command that actually demonstrated the failure.

This module deliberately does not try to invent reproduction steps: it runs
a caller-supplied test command (typically found via
:mod:`opensource_scout.repository.rules`) against the repository at a given
commit and classifies the result. Anything requiring judgment about *what*
to run is left to the caller (a human, or a future LLM-assisted planning
step) — this module's job is to execute that command safely and report
what actually happened.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy.orm import Session, sessionmaker

from opensource_scout.domain.enums import ReproductionStatus
from opensource_scout.domain.models import ReproductionReport
from opensource_scout.execution.command import CommandSpec, RiskClassification, run_command
from opensource_scout.execution.workspace import WorkspaceError, create_workspace
from opensource_scout.logging import get_logger

logger = get_logger("workflows.reproduction")

_TEST_TIMEOUT_SECONDS = 300.0
_EVIDENCE_EXCERPT_LIMIT = 500


async def reproduce_issue(
    workspace_root: Path,
    contribution_id: str,
    repository_full_name: str,
    *,
    test_command: tuple[str, ...] | None = None,
    checkout_ref: str | None = None,
    clone_url: str | None = None,
    session_factory: sessionmaker[Session] | None = None,
) -> ReproductionReport:
    """Attempt to reproduce an issue by cloning the repository and running
    ``test_command`` (e.g. ``("pytest", "-q", "tests/test_ranking.py")``).

    A non-zero exit is evidence the issue is currently reproducible
    (``CONFIRMED``); a zero exit means the command didn't demonstrate a
    failure (``NOT_REPRODUCED`` — this does *not* mean the issue is
    invalid, only that this particular command didn't show it). Without a
    test command at all, the honest answer is ``NEEDS_CLARIFICATION``, not
    a guess.
    """
    try:
        workspace = await create_workspace(
            workspace_root,
            contribution_id,
            repository_full_name,
            checkout_ref=checkout_ref,
            clone_url=clone_url,
            session_factory=session_factory,
        )
    except WorkspaceError as exc:
        logger.warning("workspace setup failed for %s: %s", repository_full_name, exc)
        return ReproductionReport(
            status=ReproductionStatus.ENVIRONMENT_BLOCKED,
            base_commit_sha="",
            summary=f"could not set up a workspace: {exc}",
            evidence=(str(exc)[:_EVIDENCE_EXCERPT_LIMIT],),
        )

    if not test_command:
        return ReproductionReport(
            status=ReproductionStatus.NEEDS_CLARIFICATION,
            base_commit_sha=workspace.base_commit_sha,
            summary=(
                "no test command was available (see "
                "opensource_scout.repository.rules); cannot automatically attempt reproduction"
            ),
        )

    result = await run_command(
        CommandSpec(
            executable=test_command[0],
            args=tuple(test_command[1:]),
            working_directory=workspace.path,
            timeout_seconds=_TEST_TIMEOUT_SECONDS,
            risk=RiskClassification.READ_ONLY,
            contribution_id=contribution_id,
        ),
        session_factory=session_factory,
    )

    if result.timed_out:
        return ReproductionReport(
            status=ReproductionStatus.ENVIRONMENT_BLOCKED,
            base_commit_sha=workspace.base_commit_sha,
            summary=f"command timed out: {' '.join(test_command)}",
            evidence=(result.stdout[-_EVIDENCE_EXCERPT_LIMIT:],),
        )

    if result.exit_code == 0:
        return ReproductionReport(
            status=ReproductionStatus.NOT_REPRODUCED,
            base_commit_sha=workspace.base_commit_sha,
            summary=f"command exited 0 — no failure observed: {' '.join(test_command)}",
            evidence=(result.stdout[-_EVIDENCE_EXCERPT_LIMIT:],),
        )

    return ReproductionReport(
        status=ReproductionStatus.CONFIRMED,
        base_commit_sha=workspace.base_commit_sha,
        summary=f"command failed (exit {result.exit_code}): {' '.join(test_command)}",
        evidence=(
            result.stdout[-_EVIDENCE_EXCERPT_LIMIT:],
            result.stderr[-_EVIDENCE_EXCERPT_LIMIT:],
        ),
    )
