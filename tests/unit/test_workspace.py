from pathlib import Path

import pytest

from opensource_scout.execution.workspace import (
    WorkspaceError,
    cleanup_workspace,
    create_workspace,
    workspace_path,
)


async def test_create_workspace_clones_and_reports_base_commit(
    tmp_path: Path, local_git_repo
) -> None:
    src = local_git_repo({"README.md": "hello"})
    workspace_root = tmp_path / "workspaces"

    info = await create_workspace(workspace_root, "c1", "octo/example", clone_url=f"file://{src}")

    assert (info.path / "README.md").read_text() == "hello"
    assert len(info.base_commit_sha) == 40
    assert info.path == workspace_path(workspace_root, "c1")


async def test_create_workspace_checks_out_requested_ref(tmp_path: Path, local_git_repo) -> None:
    src = local_git_repo({"a.txt": "1"})
    import subprocess

    subprocess.run(["git", "branch", "feature"], cwd=src, check=True)
    (src / "a.txt").write_text("2")
    subprocess.run(["git", "commit", "-aq", "-m", "second"], cwd=src, check=True)

    workspace_root = tmp_path / "workspaces"
    info = await create_workspace(
        workspace_root, "c1", "octo/example", checkout_ref="feature", clone_url=f"file://{src}"
    )
    assert (info.path / "a.txt").read_text() == "1"


async def test_create_workspace_raises_on_bad_clone_url(tmp_path: Path) -> None:
    workspace_root = tmp_path / "workspaces"
    with pytest.raises(WorkspaceError):
        await create_workspace(
            workspace_root, "c1", "octo/example", clone_url="file:///does/not/exist"
        )


def test_cleanup_workspace_removes_directory(tmp_path: Path) -> None:
    workspace_root = tmp_path / "workspaces"
    path = workspace_path(workspace_root, "c1")
    path.mkdir(parents=True)
    (path / "file.txt").write_text("x")

    cleanup_workspace(workspace_root, "c1")

    assert not path.exists()


def test_cleanup_workspace_rejects_path_traversal(tmp_path: Path) -> None:
    workspace_root = tmp_path / "workspaces"
    workspace_root.mkdir()
    with pytest.raises(WorkspaceError):
        cleanup_workspace(workspace_root, "../../etc")


def test_cleanup_workspace_is_a_noop_for_missing_directory(tmp_path: Path) -> None:
    workspace_root = tmp_path / "workspaces"
    workspace_root.mkdir()
    cleanup_workspace(workspace_root, "never-created")  # must not raise
