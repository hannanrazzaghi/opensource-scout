"""GitHub GraphQL client for batched repository metadata.

A single GraphQL query fetches repository metadata, community-health file
presence, and recent PR/issue activity together — the same information would
otherwise take five or more separate REST calls per repository, which adds
up fast across 30+ discovery candidates.
"""

from __future__ import annotations

from typing import Any

import httpx

from opensource_scout.github.errors import GitHubError, GitHubNotFoundError

GRAPHQL_URL = "https://api.github.com/graphql"

_REPOSITORY_QUERY = """
query RepositoryBundle($owner: String!, $name: String!) {
  repository(owner: $owner, name: $name) {
    nameWithOwner
    description
    url
    isArchived
    stargazerCount
    forkCount
    licenseInfo { spdxId }
    primaryLanguage { name }
    languages(first: 10, orderBy: { field: SIZE, direction: DESC }) {
      nodes { name }
    }
    repositoryTopics(first: 20) {
      nodes { topic { name } }
    }
    defaultBranchRef {
      target {
        ... on Commit { committedDate }
      }
    }
    latestRelease { publishedAt }
    openIssues: issues(states: OPEN) { totalCount }
    openPullRequests: pullRequests(states: OPEN) { totalCount }
    recentMergedPullRequests: pullRequests(
      states: MERGED
      first: 25
      orderBy: { field: UPDATED_AT, direction: DESC }
    ) {
      totalCount
      nodes {
        mergedAt
        author { login }
        authorAssociation
      }
    }
    contributing: object(expression: "HEAD:CONTRIBUTING.md") { id }
    prTemplate: object(expression: "HEAD:.github/pull_request_template.md") { id }
    issueTemplateDir: object(expression: "HEAD:.github/ISSUE_TEMPLATE") { id }
    securityPolicy: object(expression: "HEAD:SECURITY.md") { id }
  }
}
"""

_ISSUE_QUERY = """
query IssueBundle($owner: String!, $name: String!, $number: Int!) {
  repository(owner: $owner, name: $name) {
    issue(number: $number) {
      title
      url
      body
      createdAt
      updatedAt
      labels(first: 20) { nodes { name } }
      assignees(first: 10) { nodes { login } }
      comments { totalCount }
      timelineItems(itemTypes: [CROSS_REFERENCED_EVENT], first: 25) {
        nodes {
          ... on CrossReferencedEvent {
            source {
              ... on PullRequest { number state }
            }
          }
        }
      }
    }
  }
}
"""


class GraphQLClient:
    def __init__(
        self,
        *,
        token: str | None = None,
        http_client: httpx.AsyncClient | None = None,
        timeout: float = 30.0,
    ) -> None:
        headers = {"Accept": "application/vnd.github+json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self._owns_client = http_client is None
        self._client = http_client or httpx.AsyncClient(headers=headers, timeout=timeout)

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def fetch_repository_bundle(self, owner: str, name: str) -> dict[str, Any]:
        """Fetch metadata, community-health file presence, and recent merged
        PR activity for one repository in a single request.

        Raises :class:`GitHubNotFoundError` if the repository doesn't exist
        or isn't visible to the current token, and :class:`GitHubError` on
        any other GraphQL-level error.
        """
        response = await self._client.post(
            GRAPHQL_URL,
            json={"query": _REPOSITORY_QUERY, "variables": {"owner": owner, "name": name}},
        )
        response.raise_for_status()
        payload = response.json()

        errors = payload.get("errors")
        if errors:
            if any(e.get("type") == "NOT_FOUND" for e in errors):
                raise GitHubNotFoundError(f"not found: {owner}/{name}")
            raise GitHubError(f"GraphQL error for {owner}/{name}: {errors}")

        repository = payload.get("data", {}).get("repository")
        if repository is None:
            raise GitHubNotFoundError(f"not found: {owner}/{name}")
        return repository

    async def fetch_issue_bundle(self, owner: str, name: str, number: int) -> dict[str, Any]:
        """Fetch one issue's title/body/labels/assignees/comment-count and
        cross-referenced pull requests (the competing-work signal) in a
        single request. Returns ``{"issue": {...} | None}``."""
        response = await self._client.post(
            GRAPHQL_URL,
            json={
                "query": _ISSUE_QUERY,
                "variables": {"owner": owner, "name": name, "number": number},
            },
        )
        response.raise_for_status()
        payload = response.json()

        errors = payload.get("errors")
        if errors:
            if any(e.get("type") == "NOT_FOUND" for e in errors):
                raise GitHubNotFoundError(f"not found: {owner}/{name}#{number}")
            raise GitHubError(f"GraphQL error for {owner}/{name}#{number}: {errors}")

        repository = payload.get("data", {}).get("repository")
        if repository is None:
            raise GitHubNotFoundError(f"not found: {owner}/{name}#{number}")
        return repository
