from opensource_scout.domain.models import IssueCandidate
from opensource_scout.domain.profile import HANNAN_PROFILE
from opensource_scout.scoring.issue import rank_issues, rejection_reasons, score_issue


def _issue(**overrides: object) -> IssueCandidate:
    defaults: dict[str, object] = {
        "repository_full_name": "octo/example",
        "number": 1,
        "title": "Example issue",
        "url": "https://github.com/octo/example/issues/1",
        "body": "x" * 50,
        "labels": (),
        "assignees": (),
        "comment_count": 0,
    }
    defaults.update(overrides)
    return IssueCandidate(**defaults)  # type: ignore[arg-type]


def test_well_specified_good_first_issue_scores_highly() -> None:
    issue = _issue(
        title="BM25 ranking regression in retrieval engine",
        body=(
            "Steps to reproduce: run query.\n"
            "Expected: top result X.\nActual: result Y.\n```\ncode\n```"
        ),
        labels=("good first issue", "bug"),
    )
    score = score_issue(issue, HANNAN_PROFILE)
    assert not score.rejected
    assert score.total >= 60


def test_assigned_issue_is_rejected() -> None:
    issue = _issue(assignees=("someone",), has_active_assignee=True)
    reasons = rejection_reasons(issue)
    assert any("already assigned" in r for r in reasons)


def test_issue_with_competing_pr_is_rejected() -> None:
    issue = _issue(has_competing_pull_request=True)
    reasons = rejection_reasons(issue)
    assert any("pull request already addresses" in r for r in reasons)


def test_short_body_is_rejected_for_unclear_expected_behavior() -> None:
    issue = _issue(body="fix it")
    reasons = rejection_reasons(issue)
    assert any("too short" in r for r in reasons)


def test_security_labeled_issue_is_rejected() -> None:
    issue = _issue(labels=("security",))
    reasons = rejection_reasons(issue)
    assert any("security" in r for r in reasons)


def test_wontfix_labeled_issue_is_rejected() -> None:
    issue = _issue(labels=("wontfix",))
    reasons = rejection_reasons(issue)
    assert any("wontfix" in r for r in reasons)


def test_gpu_hardware_requirement_is_rejected() -> None:
    issue = _issue(body="x" * 50 + " requires multi-gpu CUDA training setup")
    reasons = rejection_reasons(issue)
    assert any("unavailable hardware" in r for r in reasons)


def test_private_data_requirement_is_rejected() -> None:
    issue = _issue(body="x" * 50 + " needs access to our confidential internal dataset")
    reasons = rejection_reasons(issue)
    assert any("private/internal data" in r for r in reasons)


def test_cosmetic_labeled_issue_is_rejected() -> None:
    issue = _issue(labels=("cosmetic",))
    reasons = rejection_reasons(issue)
    assert any("cosmetic" in r for r in reasons)


def test_epic_labeled_issue_is_rejected_for_scope() -> None:
    issue = _issue(labels=("epic",))
    reasons = rejection_reasons(issue)
    assert any("scope likely exceeds" in r for r in reasons)


def test_clean_issue_has_no_rejection_reasons() -> None:
    issue = _issue(body="x" * 50, labels=("bug",))
    assert rejection_reasons(issue) == []


def test_every_dimension_is_within_its_declared_range() -> None:
    issue = _issue(title="test", body="x" * 200, labels=("good first issue", "bug", "performance"))
    score = score_issue(issue, HANNAN_PROFILE)
    for dimension in (
        score.career_relevance,
        score.scope_clarity,
        score.acceptance_probability,
        score.technical_value,
        score.testability,
        score.schedule_fit,
    ):
        assert 0 <= dimension.value <= dimension.max_value


def test_rank_issues_sorts_eligible_before_rejected_regardless_of_score() -> None:
    high_score_rejected = _issue(
        number=1,
        title="Python Rust BM25 retrieval",
        body="x" * 200,
        labels=("good first issue", "bug"),
        assignees=("someone",),
        has_active_assignee=True,
    )
    low_score_eligible = _issue(number=2, body="x" * 50)
    ranked = rank_issues([high_score_rejected, low_score_eligible], HANNAN_PROFILE)
    assert ranked[0].issue_key.endswith("#2")
    assert not ranked[0].rejected
    assert ranked[1].rejected


def test_rank_issues_sorts_by_score_within_eligible_group() -> None:
    strong = _issue(
        number=1,
        title="BM25 retrieval performance regression",
        body="Steps to reproduce: x.\nExpected: y.\nActual: z.\n```\ncode\n```",
        labels=("good first issue", "performance"),
    )
    weak = _issue(number=2, body="x" * 50)
    ranked = rank_issues([weak, strong], HANNAN_PROFILE)
    assert ranked[0].issue_key.endswith("#1")
    assert ranked[0].total > ranked[1].total
