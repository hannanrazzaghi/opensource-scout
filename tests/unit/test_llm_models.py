import pytest
from pydantic import ValidationError

from opensource_scout.domain.llm_models import (
    ImplementationPlan,
    IssueAssessment,
    ProjectAssessment,
)


def test_project_assessment_rejects_out_of_range_career_relevance() -> None:
    with pytest.raises(ValidationError):
        ProjectAssessment(career_relevance=31, technical_depth=10, evidence=["x"], explanation="ok")


def test_project_assessment_rejects_empty_evidence() -> None:
    with pytest.raises(ValidationError):
        ProjectAssessment(career_relevance=10, technical_depth=5, evidence=[], explanation="ok")


def test_project_assessment_rejects_blank_only_evidence() -> None:
    with pytest.raises(ValidationError):
        ProjectAssessment(
            career_relevance=10, technical_depth=5, evidence=["   ", ""], explanation="ok"
        )


def test_project_assessment_rejects_empty_explanation() -> None:
    with pytest.raises(ValidationError):
        ProjectAssessment(career_relevance=10, technical_depth=5, evidence=["x"], explanation="")


def test_project_assessment_accepts_valid_input() -> None:
    a = ProjectAssessment(
        career_relevance=25, technical_depth=12, evidence=["strong overlap"], explanation="good fit"
    )
    assert a.career_relevance == 25
    assert a.risks == []


def test_issue_assessment_rejects_hours_max_below_min() -> None:
    with pytest.raises(ValidationError):
        IssueAssessment(
            scope_clarity=10,
            technical_value=5,
            estimated_hours_min=8.0,
            estimated_hours_max=2.0,
            explanation="ok",
        )


def test_issue_assessment_accepts_equal_min_and_max_hours() -> None:
    a = IssueAssessment(
        scope_clarity=10,
        technical_value=5,
        estimated_hours_min=3.0,
        estimated_hours_max=3.0,
        explanation="ok",
    )
    assert a.estimated_hours_max == 3.0


def test_issue_assessment_rejects_out_of_range_scope_clarity() -> None:
    with pytest.raises(ValidationError):
        IssueAssessment(
            scope_clarity=21,
            technical_value=5,
            estimated_hours_min=1.0,
            estimated_hours_max=2.0,
            explanation="ok",
        )


def test_implementation_plan_rejects_empty_proposed_changes() -> None:
    with pytest.raises(ValidationError):
        ImplementationPlan(
            problem="x",
            root_cause_hypothesis="y",
            proposed_changes=[],
            tests=["test_x"],
            estimated_hours=2.0,
        )


def test_implementation_plan_rejects_empty_tests() -> None:
    with pytest.raises(ValidationError):
        ImplementationPlan(
            problem="x",
            root_cause_hypothesis="y",
            proposed_changes=["change x"],
            tests=[],
            estimated_hours=2.0,
        )


def test_implementation_plan_accepts_valid_input() -> None:
    plan = ImplementationPlan(
        problem="bug in ranking",
        root_cause_hypothesis="off-by-one in score sort",
        proposed_changes=["fix sort comparator"],
        tests=["test_ranking_order"],
        estimated_hours=3.5,
    )
    assert plan.alternatives == []
    assert plan.estimated_hours == 3.5
