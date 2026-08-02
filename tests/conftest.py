"""Shared pytest fixtures."""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest


@pytest.fixture
def local_git_repo(tmp_path: Path) -> Callable[[dict[str, str]], Path]:
    """Factory fixture: given a mapping of relative path -> file content,
    creates a local git repository with one commit and returns its path.
    Used so tests can exercise real git clone/checkout behavior against a
    ``file://`` URL instead of a real network dependency."""

    def _make(files: dict[str, str]) -> Path:
        repo = tmp_path / "repo-src"
        repo.mkdir()
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True)
        for rel_path, content in files.items():
            path = repo / rel_path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
        subprocess.run(["git", "add", "."], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=repo, check=True)
        return repo

    return _make
