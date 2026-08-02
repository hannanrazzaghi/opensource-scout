"""Deterministic project scoring — plain Python, no LLM.

Every dimension is computed from :class:`RepositoryCandidate` fields against
the developer :class:`Profile`, clamped into its documented range by
:class:`~opensource_scout.domain.models.ScoreDimension` itself. Penalties are
explicit and evidenced, and the total is never allowed to be misleadingly
driven by star count alone — stars are one weak signal among many, not the
ranking key.
"""

from __future__ import annotations

from datetime import UTC, datetime

from opensource_scout.domain.models import (
    Profile,
    ProjectScore,
    RepositoryCandidate,
    ScoreDimension,
)

# Keywords that indicate hardware requirements incompatible with a CPU-only
# MacBook Air, per the developer's stated constraints.
_GPU_KEYWORDS = (
    "cuda",
    "nvidia",
    "gpu-only",
    "multi-gpu",
    "tensorrt",
    "distributed training",
    "large-scale training",
)

# Signals that a repository is a learning resource or promotional list
# rather than a project with real engineering depth to contribute to.
_LOW_DEPTH_KEYWORDS = (
    "awesome-",
    "tutorial",
    "cookbook",
    "course",
    "learning-",
    "roadmap",
    "interview-questions",
    "cheatsheet",
)

_STALE_DAYS = 365
_INACTIVE_DAYS = 180


def _text_blob(candidate: RepositoryCandidate) -> str:
    parts = [candidate.name, candidate.description or "", *candidate.topics, *candidate.languages]
    return " ".join(parts).lower()


def _keyword_overlap(text: str, keywords: tuple[str, ...]) -> list[str]:
    return [k for k in keywords if k.lower() in text]


def _score_career_relevance(candidate: RepositoryCandidate, profile: Profile) -> ScoreDimension:
    text = _text_blob(candidate)
    skill_hits = _keyword_overlap(text, profile.skills)
    interest_hits = _keyword_overlap(text, profile.interests)

    # Skills matter more than adjacent interests: up to 20 points for skill
    # overlap, up to 10 for interest overlap, each saturating rather than
    # scaling unboundedly with keyword count.
    value = min(20, len(skill_hits) * 5) + min(10, len(interest_hits) * 3)
    evidence = [f"skill match: {h}" for h in skill_hits] + [
        f"interest match: {h}" for h in interest_hits
    ]
    if not evidence:
        evidence = ["no direct skill or interest keyword overlap found"]
    return ScoreDimension(
        name="career_relevance", value=value, max_value=30, evidence=tuple(evidence)
    )


def _score_acceptance_probability(candidate: RepositoryCandidate) -> ScoreDimension:
    value = 0
    evidence: list[str] = []

    if candidate.has_contributing_guide:
        value += 6
        evidence.append("has CONTRIBUTING guide")
    if candidate.has_pr_template:
        value += 3
        evidence.append("has PR template")
    if candidate.has_issue_template:
        value += 3
        evidence.append("has issue template")
    if candidate.recent_external_contributor_prs > 0:
        points = min(6, candidate.recent_external_contributor_prs)
        value += points
        evidence.append(f"{candidate.recent_external_contributor_prs} recent external merged PRs")
    if candidate.recent_merged_prs > 0:
        value += 2
        evidence.append(f"{candidate.recent_merged_prs} recent merged PRs overall")

    return ScoreDimension(
        name="acceptance_probability", value=value, max_value=20, evidence=tuple(evidence)
    )


def _score_technical_depth(candidate: RepositoryCandidate) -> ScoreDimension:
    value = 0
    evidence: list[str] = []

    if len(candidate.languages) >= 2:
        value += 3
        evidence.append(f"polyglot codebase: {', '.join(candidate.languages[:3])}")
    if candidate.stars >= 1000:
        value += 5
        evidence.append(f"{candidate.stars} stars (established project)")
    elif candidate.stars >= 200:
        value += 3
        evidence.append(f"{candidate.stars} stars")
    if candidate.forks >= 100:
        value += 3
        evidence.append(f"{candidate.forks} forks")
    if candidate.open_issues >= 20:
        value += 2
        evidence.append(f"{candidate.open_issues} open issues (real backlog)")
    if candidate.license_spdx:
        value += 2
        evidence.append(f"licensed ({candidate.license_spdx})")

    if not evidence:
        evidence = ["no strong technical-depth signals found"]
    return ScoreDimension(
        name="technical_depth", value=value, max_value=15, evidence=tuple(evidence)
    )


def _score_maintainer_activity(candidate: RepositoryCandidate, *, now: datetime) -> ScoreDimension:
    value = 0
    evidence: list[str] = []

    if candidate.latest_commit_at is not None:
        days_since_commit = (now - candidate.latest_commit_at).days
        if days_since_commit <= 30:
            value += 7
            evidence.append(f"committed within {days_since_commit} days")
        elif days_since_commit <= _INACTIVE_DAYS:
            value += 4
            evidence.append(f"committed within {days_since_commit} days")
        else:
            evidence.append(f"last commit {days_since_commit} days ago")
    else:
        evidence.append("no commit date available")

    if candidate.latest_release_at is not None:
        days_since_release = (now - candidate.latest_release_at).days
        if days_since_release <= 180:
            value += 4
            evidence.append(f"released within {days_since_release} days")

    if candidate.recent_merged_prs >= 10:
        value += 4
        evidence.append(f"{candidate.recent_merged_prs} recently merged PRs")
    elif candidate.recent_merged_prs >= 3:
        value += 2
        evidence.append(f"{candidate.recent_merged_prs} recently merged PRs")

    return ScoreDimension(
        name="maintainer_activity", value=value, max_value=15, evidence=tuple(evidence)
    )


def _score_hardware_compatibility(candidate: RepositoryCandidate) -> ScoreDimension:
    text = _text_blob(candidate)
    gpu_hits = _keyword_overlap(text, _GPU_KEYWORDS)

    value = 10
    evidence: list[str] = []
    if gpu_hits:
        value -= min(10, len(gpu_hits) * 4)
        evidence.append(f"GPU/large-scale-training signals: {', '.join(gpu_hits)}")
    else:
        evidence.append("no GPU or large-scale-training signals found")

    cpu_friendly_languages = {"python", "rust", "go", "typescript", "javascript", "c", "c++"}
    if any(lang.lower() in cpu_friendly_languages for lang in candidate.languages):
        evidence.append("uses a CPU-friendly primary language")

    value = max(0, value)
    return ScoreDimension(
        name="hardware_compatibility", value=value, max_value=10, evidence=tuple(evidence)
    )


def _score_repeat_contribution_value(candidate: RepositoryCandidate) -> ScoreDimension:
    value = 0
    evidence: list[str] = []

    if candidate.open_issues >= 30:
        value += 4
        evidence.append(f"{candidate.open_issues} open issues — room for repeat contributions")
    elif candidate.open_issues >= 10:
        value += 2
        evidence.append(f"{candidate.open_issues} open issues")

    if candidate.recent_merged_prs >= 10:
        value += 3
        evidence.append("actively merging PRs — an ongoing project, not a one-off fix")

    if candidate.stars >= 500:
        value += 3
        evidence.append("established enough to be a durable résumé credential")

    return ScoreDimension(
        name="repeat_contribution_value",
        value=min(10, value),
        max_value=10,
        evidence=tuple(evidence),
    )


def _penalties(candidate: RepositoryCandidate, *, now: datetime) -> tuple[list[str], int]:
    reasons: list[str] = []
    points = 0
    text = _text_blob(candidate)

    if candidate.archived:
        reasons.append("repository is archived")
        points += 100  # effectively zeroes the total

    if not candidate.license_spdx:
        reasons.append("no OSS license detected")
        points += 15

    if candidate.latest_commit_at is not None:
        days_since_commit = (now - candidate.latest_commit_at).days
        if days_since_commit > _STALE_DAYS:
            reasons.append(f"no commits in {days_since_commit} days (stale)")
            points += 10

    if candidate.open_pull_requests > 20 and candidate.recent_external_contributor_prs == 0:
        reasons.append("many open PRs with no recent external contributor merges")
        points += 5

    low_depth_hits = _keyword_overlap(text, _LOW_DEPTH_KEYWORDS)
    if low_depth_hits:
        reasons.append(f"looks like a tutorial/list repo: {', '.join(low_depth_hits)}")
        points += 10

    gpu_hits = _keyword_overlap(text, _GPU_KEYWORDS)
    if len(gpu_hits) >= 2:
        reasons.append("strong GPU/large-scale-training focus")
        points += 5

    return reasons, points


def score_project(
    candidate: RepositoryCandidate, profile: Profile, *, now: datetime | None = None
) -> ProjectScore:
    """Compute a full, evidence-backed :class:`ProjectScore` for one
    repository candidate. Deterministic: the same inputs always produce the
    same score."""
    at = now or datetime.now(UTC)
    penalties, penalty_points = _penalties(candidate, now=at)

    return ProjectScore(
        repository_full_name=candidate.full_name,
        career_relevance=_score_career_relevance(candidate, profile),
        acceptance_probability=_score_acceptance_probability(candidate),
        technical_depth=_score_technical_depth(candidate),
        maintainer_activity=_score_maintainer_activity(candidate, now=at),
        hardware_compatibility=_score_hardware_compatibility(candidate),
        repeat_contribution_value=_score_repeat_contribution_value(candidate),
        penalties=tuple(penalties),
        penalty_points=penalty_points,
    )


def rank_projects(
    candidates: list[RepositoryCandidate], profile: Profile, *, now: datetime | None = None
) -> list[ProjectScore]:
    """Score every candidate and return them sorted by total score,
    highest first. Ties break by star count only as a last resort."""
    scores = [score_project(c, profile, now=now) for c in candidates]
    stars_by_name = {c.full_name: c.stars for c in candidates}
    scores.sort(key=lambda s: (s.total, stars_by_name[s.repository_full_name]), reverse=True)
    return scores
