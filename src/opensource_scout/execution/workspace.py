"""Isolated per-contribution workspaces: clone, checkout, and cleanup.

Every reproduction or implementation attempt gets its own directory under
``settings.workspace_dir`` so nothing it does can affect another
contribution's state, and so the whole thing can be deleted in one step.
Cloning is read-only against GitHub (fetching a public repository, never
pushing), which is why it doesn't require the external-action approval that
pushing a branch or opening a PR does.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.orm import Session, sessionmaker

from opensource_scout.execution.command import CommandSpec, RiskClassification, run_command
from opensource_scout.logging import get_logger

logger = get_logger("execution.workspace")

_CLONE_TIMEOUT_SECONDS = 180.0


class WorkspaceError(Exception):
    """Raised when workspace setup (clone/checkout) fails."""


@dataclass(frozen=True)
class WorkspaceInfo:
    path: Path
    repository_full_name: str
    base_commit_sha: str


def workspace_path(workspace_root: Path, contribution_id: str) -> Path:
    return workspace_root / contribution_id


async def create_workspace(
    workspace_root: Path,
    contribution_id: str,
    repository_full_name: str,
    *,
    checkout_ref: str | None = None,
    session_factory: sessionmaker[Session] | None = None,
    clone_url: str | None = None,
) -> WorkspaceInfo:
    """Clone ``repository_full_name`` into an isolated workspace directory
    and check out ``checkout_ref`` (a branch, tag, or commit SHA) if given,
    otherwise leave it at the default branch's HEAD.

    ``clone_url`` defaults to the repository's GitHub URL; tests pass a
    local ``file://`` URL to avoid a real network dependency.

    Raises :class:`WorkspaceError` if the clone or checkout fails.
    """
    path = workspace_path(workspace_root, contribution_id)
    path.mkdir(parents=True, exist_ok=True)

    clone_url = clone_url or f"https://github.com/{repository_full_name}.git"
    clone_result = await run_command(
        CommandSpec(
            executable="git",
            args=("clone", "--depth", "50", clone_url, "."),
            working_directory=path,
            timeout_seconds=_CLONE_TIMEOUT_SECONDS,
            network_required=True,
            risk=RiskClassification.READ_ONLY,
            contribution_id=contribution_id,
        ),
        session_factory=session_factory,
    )
    if clone_result.exit_code != 0:
        raise WorkspaceError(f"git clone failed: {clone_result.stderr}")

    if checkout_ref is not None:
        checkout_result = await run_command(
            CommandSpec(
                executable="git",
                args=("checkout", checkout_ref),
                working_directory=path,
                risk=RiskClassification.READ_ONLY,
                contribution_id=contribution_id,
            ),
            session_factory=session_factory,
        )
        if checkout_result.exit_code != 0:
            raise WorkspaceError(f"git checkout {checkout_ref!r} failed: {checkout_result.stderr}")

    sha_result = await run_command(
        CommandSpec(
            executable="git",
            args=("rev-parse", "HEAD"),
            working_directory=path,
            risk=RiskClassification.READ_ONLY,
            contribution_id=contribution_id,
        ),
        session_factory=session_factory,
    )
    if sha_result.exit_code != 0:
        raise WorkspaceError(f"git rev-parse HEAD failed: {sha_result.stderr}")

    return WorkspaceInfo(
        path=path,
        repository_full_name=repository_full_name,
        base_commit_sha=sha_result.stdout.strip(),
    )


def cleanup_workspace(workspace_root: Path, contribution_id: str) -> None:
    """Delete a workspace directory. Refuses to act outside
    ``workspace_root`` even if ``contribution_id`` were somehow crafted to
    contain path-traversal segments."""
    path = workspace_path(workspace_root, contribution_id).resolve()
    root = workspace_root.resolve()
    if not str(path).startswith(str(root)):
        raise WorkspaceError(f"refusing to delete path outside workspace root: {path}")
    if path.exists():
        shutil.rmtree(path)
        logger.info("cleaned up workspace %s", path)
