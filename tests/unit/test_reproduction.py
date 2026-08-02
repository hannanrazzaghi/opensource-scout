from pathlib import Path

from opensource_scout.domain.enums import ReproductionStatus
from opensource_scout.workflows.reproduction import reproduce_issue


async def test_failing_command_is_confirmed(tmp_path: Path, local_git_repo) -> None:
    src = local_git_repo({"test_broken.py": "def test_fails():\n    assert 1 == 2\n"})
    report = await reproduce_issue(
        tmp_path / "workspaces",
        "c1",
        "octo/example",
        test_command=("python3", "-m", "pytest", "-q", "test_broken.py"),
        clone_url=f"file://{src}",
    )
    assert report.status == ReproductionStatus.CONFIRMED
    assert report.base_commit_sha
    assert report.evidence


async def test_passing_command_is_not_reproduced(tmp_path: Path, local_git_repo) -> None:
    src = local_git_repo({"test_ok.py": "def test_passes():\n    assert 1 == 1\n"})
    report = await reproduce_issue(
        tmp_path / "workspaces",
        "c1",
        "octo/example",
        test_command=("python3", "-m", "pytest", "-q", "test_ok.py"),
        clone_url=f"file://{src}",
    )
    assert report.status == ReproductionStatus.NOT_REPRODUCED


async def test_missing_test_command_needs_clarification(tmp_path: Path, local_git_repo) -> None:
    src = local_git_repo({"README.md": "hi"})
    report = await reproduce_issue(
        tmp_path / "workspaces",
        "c1",
        "octo/example",
        test_command=None,
        clone_url=f"file://{src}",
    )
    assert report.status == ReproductionStatus.NEEDS_CLARIFICATION
    assert report.base_commit_sha  # workspace setup still succeeded


async def test_bad_clone_url_is_environment_blocked(tmp_path: Path) -> None:
    report = await reproduce_issue(
        tmp_path / "workspaces",
        "c1",
        "octo/example",
        test_command=("pytest",),
        clone_url="file:///does/not/exist",
    )
    assert report.status == ReproductionStatus.ENVIRONMENT_BLOCKED
    assert report.base_commit_sha == ""
