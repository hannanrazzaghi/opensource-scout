from datetime import UTC, datetime, timedelta

from opensource_scout.domain.models import RepositoryCandidate
from opensource_scout.domain.profile import HANNAN_PROFILE
from opensource_scout.scoring.project import rank_projects, score_project

NOW = datetime(2026, 8, 2, tzinfo=UTC)


def _candidate(**overrides: object) -> RepositoryCandidate:
    defaults: dict[str, object] = {
        "owner": "octo",
        "name": "example",
        "url": "https://github.com/octo/example",
        "description": "",
        "languages": (),
        "topics": (),
        "license_spdx": "MIT",
        "stars": 0,
        "forks": 0,
        "archived": False,
    }
    defaults.update(overrides)
    return RepositoryCandidate(**defaults)  # type: ignore[arg-type]


def test_relevant_maintained_project_scores_highly() -> None:
    candidate = _candidate(
        description="BM25 code search and retrieval engine with tree-sitter parsing",
        languages=("Python", "Rust"),
        topics=("code-search", "bm25", "retrieval"),
        stars=2000,
        forks=200,
        latest_commit_at=NOW - timedelta(days=5),
        latest_release_at=NOW - timedelta(days=20),
        open_issues=50,
        open_pull_requests=5,
        recent_merged_prs=20,
        recent_external_contributor_prs=8,
        has_contributing_guide=True,
        has_pr_template=True,
        has_issue_template=True,
    )
    score = score_project(candidate, HANNAN_PROFILE, now=NOW)
    assert score.total >= 70
    assert score.penalty_points == 0


def test_archived_repository_is_zeroed_out() -> None:
    candidate = _candidate(stars=50000, archived=True, license_spdx=None)
    score = score_project(candidate, HANNAN_PROFILE, now=NOW)
    assert score.total == 0
    assert "repository is archived" in score.penalties


def test_tutorial_repo_is_penalized_despite_high_stars() -> None:
    candidate = _candidate(
        name="awesome-llm-tutorials",
        description="A curated awesome-list of tutorials and cookbooks",
        topics=("tutorial", "awesome-list"),
        stars=40000,
        license_spdx=None,
    )
    score = score_project(candidate, HANNAN_PROFILE, now=NOW)
    assert score.penalty_points > 0
    assert any("tutorial" in p for p in score.penalties)


def test_gpu_heavy_project_loses_hardware_compatibility_points() -> None:
    candidate = _candidate(
        description="Multi-GPU CUDA distributed training framework using NVIDIA TensorRT",
        languages=("Python",),
        stars=500,
    )
    score = score_project(candidate, HANNAN_PROFILE, now=NOW)
    assert score.hardware_compatibility.value < 10


def test_cpu_friendly_project_gets_full_hardware_score() -> None:
    candidate = _candidate(languages=("Python", "Rust"), description="A CPU-only tool")
    score = score_project(candidate, HANNAN_PROFILE, now=NOW)
    assert score.hardware_compatibility.value == 10


def test_stale_project_is_penalized() -> None:
    candidate = _candidate(latest_commit_at=NOW - timedelta(days=800))
    score = score_project(candidate, HANNAN_PROFILE, now=NOW)
    assert any("stale" in p for p in score.penalties)


def test_no_license_is_penalized() -> None:
    candidate = _candidate(license_spdx=None)
    score = score_project(candidate, HANNAN_PROFILE, now=NOW)
    assert any("no OSS license" in p for p in score.penalties)


def test_ignored_external_prs_are_penalized() -> None:
    candidate = _candidate(open_pull_requests=25, recent_external_contributor_prs=0)
    score = score_project(candidate, HANNAN_PROFILE, now=NOW)
    assert any("no recent external contributor merges" in p for p in score.penalties)


def test_rank_projects_sorts_by_score_descending_not_stars() -> None:
    high_score_low_stars = _candidate(
        name="relevant",
        description="Python Rust BM25 tree-sitter retrieval graph algorithms",
        languages=("Python", "Rust"),
        stars=100,
        latest_commit_at=NOW - timedelta(days=2),
        has_contributing_guide=True,
        recent_merged_prs=15,
        recent_external_contributor_prs=5,
        open_issues=40,
    )
    low_score_high_stars = _candidate(
        name="irrelevant-archived",
        stars=100_000,
        archived=True,
        license_spdx=None,
    )
    ranked = rank_projects([low_score_high_stars, high_score_low_stars], HANNAN_PROFILE, now=NOW)
    assert ranked[0].repository_full_name == "octo/relevant"
    assert ranked[0].total > ranked[1].total


def test_every_dimension_is_within_its_declared_range() -> None:
    candidate = _candidate(
        description="cuda gpu training tutorial awesome-list",
        stars=10,
        archived=False,
    )
    score = score_project(candidate, HANNAN_PROFILE, now=NOW)
    for dimension in (
        score.career_relevance,
        score.acceptance_probability,
        score.technical_depth,
        score.maintainer_activity,
        score.hardware_compatibility,
        score.repeat_contribution_value,
    ):
        assert 0 <= dimension.value <= dimension.max_value


def test_total_never_negative_even_with_many_penalties() -> None:
    candidate = _candidate(
        description="cuda multi-gpu nvidia tensorrt distributed training tutorial awesome-list",
        archived=True,
        license_spdx=None,
        latest_commit_at=NOW - timedelta(days=900),
        open_pull_requests=50,
        recent_external_contributor_prs=0,
    )
    score = score_project(candidate, HANNAN_PROFILE, now=NOW)
    assert score.total == 0
