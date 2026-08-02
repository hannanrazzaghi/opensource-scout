"""Issue discovery and competing-work detection for a selected repository.

REST lists candidate issues cheaply (label-filtered and a recent-unlabeled
sweep); each surviving candidate is then enriched with a single GraphQL
query for assignees, comment count, and cross-referenced pull requests — the
signal used to detect that someone is already working the issue.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

from opensource_scout.domain.models import IssueCandidate
from opensource_scout.github.client import GitHubRestClient
from opensource_scout.github.errors import GitHubError, GitHubNotFoundError
from opensource_scout.github.graphql import GraphQLClient
from opensource_scout.logging import get_logger

logger = get_logger("github.issues")

TARGET_LABELS: tuple[str, ...] = (
    "good first issue",
    "help wanted",
    "bug",
    "performance",
    "testing",
    "reliability",
    "developer experience",
    "refactor",
    "technical debt",
    "needs reproduction",
)


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


async def _list_candidate_numbers(
    client: GitHubRestClient, owner: str, name: str, *, max_issues: int = 60
) -> list[int]:
    """List up to ``max_issues`` open issue numbers: every target-labeled
    issue plus a sweep of recent unlabeled ones, excluding pull requests
    (the REST issues endpoint returns both)."""
    seen: dict[int, None] = {}

    async def _collect(params: dict[str, Any]) -> None:
        async for item in client.paginate(f"/repos/{owner}/{name}/issues", params=params):
            if "pull_request" in item:
                continue
            seen.setdefault(item["number"], None)
            if len(seen) >= max_issues:
                return

    for label in TARGET_LABELS:
        if len(seen) >= max_issues:
            break
        try:
            await _collect({"state": "open", "labels": label, "per_page": 20})
        except GitHubError as exc:
            logger.warning("label search failed for %r, skipping: %s", label, exc)

    if len(seen) < max_issues:
        try:
            await _collect(
                {"state": "open", "sort": "updated", "direction": "desc", "per_page": 30}
            )
        except GitHubError as exc:
            logger.warning("recent-issue sweep failed: %s", exc)

    return list(seen.keys())[:max_issues]


def _candidate_from_bundle(
    repository_full_name: str, number: int, issue: dict[str, Any]
) -> IssueCandidate:
    labels = tuple(n["name"] for n in issue.get("labels", {}).get("nodes", []))
    assignees = tuple(n["login"] for n in issue.get("assignees", {}).get("nodes", []))
    timeline_nodes = issue.get("timelineItems", {}).get("nodes", [])
    linked_prs = tuple(
        str(source["number"])
        for node in timeline_nodes
        if (source := node.get("source")) and source.get("number") is not None
    )
    has_competing_pr = any(
        (node.get("source") or {}).get("state") == "OPEN" for node in timeline_nodes
    )

    return IssueCandidate(
        repository_full_name=repository_full_name,
        number=number,
        title=issue.get("title", ""),
        url=issue.get("url", ""),
        body=issue.get("body") or "",
        labels=labels,
        assignees=assignees,
        linked_pull_requests=linked_prs,
        comment_count=issue.get("comments", {}).get("totalCount", 0),
        created_at=_parse_datetime(issue.get("createdAt")),
        updated_at=_parse_datetime(issue.get("updatedAt")),
        has_active_assignee=len(assignees) > 0,
        has_competing_pull_request=has_competing_pr,
    )


async def discover_issues(
    rest_client: GitHubRestClient,
    graphql_client: GraphQLClient,
    owner: str,
    name: str,
    *,
    max_issues: int = 60,
    enrichment_concurrency: int = 4,
) -> list[IssueCandidate]:
    """Discover open issues for one repository, enriched with competing-work
    signals. Repository-not-found propagates; individual issue lookup
    failures are logged and skipped."""
    numbers = await _list_candidate_numbers(rest_client, owner, name, max_issues=max_issues)
    repository_full_name = f"{owner}/{name}"
    semaphore = asyncio.Semaphore(enrichment_concurrency)

    async def _enrich(number: int) -> IssueCandidate | None:
        async with semaphore:
            try:
                response = await graphql_client.fetch_issue_bundle(owner, name, number)
            except GitHubNotFoundError:
                logger.info("skipping issue #%d: no longer found", number)
                return None
        issue = response.get("issue")
        if issue is None:
            return None
        return _candidate_from_bundle(repository_full_name, number, issue)

    results = await asyncio.gather(*(_enrich(n) for n in numbers))
    return [c for c in results if c is not None]
