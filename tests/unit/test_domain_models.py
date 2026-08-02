from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from opensource_scout.domain.models import ContributionRecord, ProjectScore, ScoreDimension


def _dim(name: str, value: int, max_value: int) -> ScoreDimension:
    return ScoreDimension(name=name, value=value, max_value=max_value, evidence=("evidence",))


def test_score_dimension_rejects_value_above_max() -> None:
    with pytest.raises(ValidationError):
        ScoreDimension(name="career_relevance", value=31, max_value=30)


def test_score_dimension_rejects_negative_value() -> None:
    with pytest.raises(ValidationError):
        ScoreDimension(name="career_relevance", value=-1, max_value=30)


def test_score_dimension_accepts_boundary_values() -> None:
    assert ScoreDimension(name="x", value=0, max_value=30).value == 0
    assert ScoreDimension(name="x", value=30, max_value=30).value == 30


def test_project_score_total_sums_dimensions_and_applies_penalties() -> None:
    score = ProjectScore(
        repository_full_name="octo/example",
        career_relevance=_dim("career_relevance", 25, 30),
        acceptance_probability=_dim("acceptance_probability", 15, 20),
        technical_depth=_dim("technical_depth", 10, 15),
        maintainer_activity=_dim("maintainer_activity", 10, 15),
        hardware_compatibility=_dim("hardware_compatibility", 8, 10),
        repeat_contribution_value=_dim("repeat_contribution_value", 5, 10),
        penalties=("archived repository",),
        penalty_points=10,
    )
    # 25 + 15 + 10 + 10 + 8 + 5 = 73, minus 10 penalty points = 63
    assert score.total == 63


def test_project_score_total_never_goes_negative() -> None:
    score = ProjectScore(
        repository_full_name="octo/example",
        career_relevance=_dim("career_relevance", 0, 30),
        acceptance_probability=_dim("acceptance_probability", 0, 20),
        technical_depth=_dim("technical_depth", 0, 15),
        maintainer_activity=_dim("maintainer_activity", 0, 15),
        hardware_compatibility=_dim("hardware_compatibility", 0, 10),
        repeat_contribution_value=_dim("repeat_contribution_value", 0, 10),
        penalty_points=999,
    )
    assert score.total == 0


def test_resume_bullet_requires_merged_state() -> None:
    now = datetime.now(UTC)
    with pytest.raises(ValidationError):
        ContributionRecord(
            contribution_id="c1",
            repository_full_name="octo/example",
            state="IMPLEMENTING",
            created_at=now,
            updated_at=now,
            resume_bullet="Fixed a bug in octo/example",
        )


def test_resume_bullet_allowed_once_merged() -> None:
    now = datetime.now(UTC)
    record = ContributionRecord(
        contribution_id="c1",
        repository_full_name="octo/example",
        state="MERGED",
        created_at=now,
        updated_at=now,
        resume_bullet="Fixed a bug in octo/example",
    )
    assert record.resume_bullet is not None
