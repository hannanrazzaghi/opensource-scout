"""Deterministic issue scoring and rejection — plain Python, no LLM.

Mirrors :mod:`opensource_scout.scoring.project`: every dimension is
evidence-backed and range-validated by
:class:`~opensource_scout.domain.models.ScoreDimension`. Rejection is a
separate, explicit step — an issue can score well on every dimension and
still be rejected outright for reasons scoring alone shouldn't paper over
(someone's already working it, it needs hardware we don't have, and so on).
"""

from __future__ import annotations

from opensource_scout.domain.models import IssueCandidate, IssueScore, Profile, ScoreDimension
from opensource_scout.scoring.keywords import GPU_KEYWORDS, keyword_overlap

_MIN_BODY_LENGTH = 40

_PRIVATE_DATA_KEYWORDS = ("proprietary", "confidential", "internal only", "internal-only")
_SCOPE_TOO_LARGE_LABELS = {"epic", "major-rewrite", "rfc", "breaking-change"}
_REJECTED_DIRECTION_LABELS = {"wontfix", "invalid", "duplicate"}
_SECURITY_LABELS = {"security", "vulnerability"}
_UNTESTABLE_LABELS = {"question", "discussion"}
_COSMETIC_LABELS = {"cosmetic", "typo"}

_GOOD_ENTRY_LABELS = {"good first issue", "help wanted"}
_TECHNICAL_VALUE_LABELS = {
    "performance",
    "reliability",
    "technical debt",
    "refactor",
    "testing",
    "bug",
}
_TESTABILITY_LABELS = {"testing", "bug", "reliability"}


def _text_blob(candidate: IssueCandidate) -> str:
    return f"{candidate.title} {candidate.body}".lower()


def _labels_lower(candidate: IssueCandidate) -> set[str]:
    return {label.lower() for label in candidate.labels}


def rejection_reasons(candidate: IssueCandidate) -> list[str]:
    """Explicit, evidenced reasons this issue should not be pursued. An
    empty list means nothing here disqualifies it — not that it's a good
    match, which is what the score is for."""
    reasons: list[str] = []
    labels = _labels_lower(candidate)
    text = _text_blob(candidate)

    if candidate.has_active_assignee:
        reasons.append(f"already assigned to {', '.join(candidate.assignees)}")
    if candidate.has_competing_pull_request:
        reasons.append("an open pull request already addresses this issue")
    if len(candidate.body.strip()) < _MIN_BODY_LENGTH:
        reasons.append("issue body is too short to establish clear expected behavior")

    private_hits = keyword_overlap(text, _PRIVATE_DATA_KEYWORDS)
    if private_hits:
        reasons.append(f"appears to require private/internal data: {', '.join(private_hits)}")

    gpu_hits = keyword_overlap(text, GPU_KEYWORDS)
    if gpu_hits:
        reasons.append(f"appears to require unavailable hardware: {', '.join(gpu_hits)}")

    if labels & _SCOPE_TOO_LARGE_LABELS:
        reasons.append(f"scope likely exceeds available time: {labels & _SCOPE_TOO_LARGE_LABELS}")
    if labels & _REJECTED_DIRECTION_LABELS:
        reasons.append(f"maintainers marked this as: {labels & _REJECTED_DIRECTION_LABELS}")
    if labels & _SECURITY_LABELS:
        reasons.append("labeled as a security issue — requires private disclosure, not a PR")
    if labels & _UNTESTABLE_LABELS:
        reasons.append("labeled as a question/discussion, not a well-defined code change")
    if labels & _COSMETIC_LABELS:
        reasons.append("primarily cosmetic")

    return reasons


def _score_career_relevance(candidate: IssueCandidate, profile: Profile) -> ScoreDimension:
    text = _text_blob(candidate)
    skill_hits = keyword_overlap(text, profile.skills)
    interest_hits = keyword_overlap(text, profile.interests)
    value = min(15, len(skill_hits) * 5) + min(10, len(interest_hits) * 3)
    evidence = [f"skill match: {h}" for h in skill_hits] + [
        f"interest match: {h}" for h in interest_hits
    ]
    if not evidence:
        evidence = ["no direct skill or interest keyword overlap found"]
    return ScoreDimension(
        name="career_relevance", value=value, max_value=25, evidence=tuple(evidence)
    )


def _score_scope_clarity(candidate: IssueCandidate) -> ScoreDimension:
    value = 0
    evidence: list[str] = []
    body = candidate.body

    if len(body.strip()) >= _MIN_BODY_LENGTH:
        value += 6
        evidence.append(f"body has {len(body.strip())} characters of detail")
    if "```" in body:
        value += 4
        evidence.append("includes a code block")
    lowered = body.lower()
    if "steps to reproduce" in lowered or "to reproduce" in lowered:
        value += 5
        evidence.append("includes explicit reproduction steps")
    if "expected" in lowered and "actual" in lowered:
        value += 5
        evidence.append("states both expected and actual behavior")

    if not evidence:
        evidence = ["issue body provides little structure to work from"]
    return ScoreDimension(name="scope_clarity", value=value, max_value=20, evidence=tuple(evidence))


def _score_acceptance_probability(candidate: IssueCandidate) -> ScoreDimension:
    value = 0
    evidence: list[str] = []
    labels = _labels_lower(candidate)

    hits = labels & _GOOD_ENTRY_LABELS
    if hits:
        value += 10
        evidence.append(f"labeled: {', '.join(sorted(hits))}")
    if not candidate.has_active_assignee:
        value += 5
        evidence.append("no active assignee")
    if not candidate.has_competing_pull_request:
        value += 5
        evidence.append("no competing open pull request")

    return ScoreDimension(
        name="acceptance_probability", value=value, max_value=20, evidence=tuple(evidence)
    )


def _score_technical_value(candidate: IssueCandidate) -> ScoreDimension:
    value = 0
    evidence: list[str] = []
    labels = _labels_lower(candidate)

    hits = labels & _TECHNICAL_VALUE_LABELS
    if hits:
        value += min(15, len(hits) * 5)
        evidence.append(f"labeled: {', '.join(sorted(hits))}")
    if not evidence:
        evidence = ["no technical-value labels found"]
    return ScoreDimension(
        name="technical_value", value=value, max_value=15, evidence=tuple(evidence)
    )


def _score_testability(candidate: IssueCandidate) -> ScoreDimension:
    value = 0
    evidence: list[str] = []
    labels = _labels_lower(candidate)
    lowered = candidate.body.lower()

    if labels & _TESTABILITY_LABELS:
        value += 5
        evidence.append(f"labeled: {', '.join(sorted(labels & _TESTABILITY_LABELS))}")
    if "expected" in lowered and "actual" in lowered:
        value += 5
        evidence.append("has a clear expected-vs-actual distinction to assert against")

    if not evidence:
        evidence = ["no clear signal that this can be tested objectively"]
    return ScoreDimension(name="testability", value=value, max_value=10, evidence=tuple(evidence))


def _score_schedule_fit(candidate: IssueCandidate) -> ScoreDimension:
    value = 5
    evidence: list[str] = ["baseline: assumed moderate scope"]
    labels = _labels_lower(candidate)

    if "good first issue" in labels:
        value += 5
        evidence = ["labeled good first issue — fits a 3-5 hour weekly budget"]
    elif labels & _SCOPE_TOO_LARGE_LABELS:
        value = 0
        evidence = [f"labeled as large scope: {labels & _SCOPE_TOO_LARGE_LABELS}"]
    elif candidate.comment_count > 20:
        value = 2
        evidence = [f"{candidate.comment_count} comments suggest a contentious/complex issue"]

    return ScoreDimension(name="schedule_fit", value=value, max_value=10, evidence=tuple(evidence))


def score_issue(candidate: IssueCandidate, profile: Profile) -> IssueScore:
    """Compute a full, evidence-backed :class:`IssueScore`. Deterministic:
    the same inputs always produce the same score and rejection reasons."""
    issue_key = f"{candidate.repository_full_name}#{candidate.number}"
    return IssueScore(
        issue_key=issue_key,
        career_relevance=_score_career_relevance(candidate, profile),
        scope_clarity=_score_scope_clarity(candidate),
        acceptance_probability=_score_acceptance_probability(candidate),
        technical_value=_score_technical_value(candidate),
        testability=_score_testability(candidate),
        schedule_fit=_score_schedule_fit(candidate),
        rejection_reasons=tuple(rejection_reasons(candidate)),
    )


def rank_issues(candidates: list[IssueCandidate], profile: Profile) -> list[IssueScore]:
    """Score every candidate and return them sorted by total score,
    highest first, with rejected issues sorted to the end regardless of
    their numeric score."""
    scores = [score_issue(c, profile) for c in candidates]
    scores.sort(key=lambda s: (not s.rejected, s.total), reverse=True)
    return scores
