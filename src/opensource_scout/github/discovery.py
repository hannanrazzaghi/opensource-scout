"""Repository discovery across the developer's target technical domains.

Two-phase: cheap REST search calls first (broad, deduped, tagged with which
domain query surfaced each repository), then GraphQL enrichment only for the
deduped set — this is far cheaper than running the expensive per-repository
query against every raw search hit before deduplication.
"""

from __future__ import annotations

import asyncio
from datetime import datetime

from opensource_scout.domain.models import RepositoryCandidate
from opensource_scout.github.client import GitHubRestClient
from opensource_scout.github.errors import GitHubError, GitHubNotFoundError
from opensource_scout.github.graphql import GraphQLClient
from opensource_scout.logging import get_logger

logger = get_logger("github.discovery")

MIN_CANDIDATES = 30

# Free-text + qualifier search queries covering the developer's target
# domains (see docs/architecture.md). Each is capped to GitHub's excellent-
# match search behavior via `sort=updated` so results stay maintained
# projects, not abandoned ones.
DISCOVERY_QUERIES: tuple[str, ...] = (
    "llm infrastructure in:name,description,topics archived:false stars:>50",
    "ai agents framework in:name,description,topics archived:false stars:>50",
    "code intelligence in:name,description,topics archived:false stars:>30",
    "code search engine in:name,description,topics archived:false stars:>30",
    "retrieval augmented generation in:description archived:false stars:>50",
    "search ranking algorithm in:description archived:false stars:>30",
    "bm25 in:name,description,topics archived:false",
    "graph algorithms library in:description,topics archived:false stars:>20",
    "tree-sitter in:name,description,topics archived:false stars:>20",
    "parser combinator OR compiler frontend in:description archived:false stars:>30",
    "static analysis tool in:description,topics archived:false stars:>30",
    "llm evaluation OR model evaluation framework in:description archived:false stars:>30",
    "model serving inference in:description,topics archived:false stars:>50",
    "developer tooling cli in:description,topics archived:false stars:>50",
    "embedded database engine in:description archived:false stars:>30",
    "distributed systems consensus in:description archived:false stars:>30",
    "performance profiler in:description,topics archived:false stars:>30",
    "language:Python topics:developer-tools archived:false stars:>100",
    "language:Rust topics:developer-tools archived:false stars:>100",
    "pyo3 OR maturin in:name,description,topics archived:false",
)

_OWNER_ASSOCIATIONS = {"OWNER", "MEMBER", "COLLABORATOR"}


async def _search_domain(
    client: GitHubRestClient, query: str, *, max_items: int = 30
) -> list[dict]:
    items: list[dict] = []
    try:
        async for item in client.paginate(
            "/search/repositories", params={"q": query, "sort": "updated", "order": "desc"}
        ):
            items.append(item)
            if len(items) >= max_items:
                break
    except GitHubError as exc:
        logger.warning("search query failed, skipping: %r (%s)", query, exc)
    return items


async def _search_all_domains(
    client: GitHubRestClient, queries: tuple[str, ...]
) -> tuple[dict[str, dict], dict[str, set[str]]]:
    results = await asyncio.gather(*(_search_domain(client, q) for q in queries))

    by_full_name: dict[str, dict] = {}
    discovered_via: dict[str, set[str]] = {}
    for query, items in zip(queries, results, strict=True):
        for item in items:
            full_name = item["full_name"]
            by_full_name.setdefault(full_name, item)
            discovered_via.setdefault(full_name, set()).add(query)
    return by_full_name, discovered_via


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _candidate_from_bundle(
    full_name: str, bundle: dict, *, discovered_via: tuple[str, ...]
) -> RepositoryCandidate:
    owner, name = full_name.split("/", 1)
    license_info = bundle.get("licenseInfo") or {}
    default_branch = bundle.get("defaultBranchRef") or {}
    target = default_branch.get("target") or {}
    latest_release = bundle.get("latestRelease") or {}
    merged = bundle.get("recentMergedPullRequests") or {}
    merged_nodes = merged.get("nodes") or []
    external_prs = sum(
        1 for n in merged_nodes if n.get("authorAssociation") not in _OWNER_ASSOCIATIONS
    )

    return RepositoryCandidate(
        owner=owner,
        name=name,
        url=bundle.get("url") or f"https://github.com/{full_name}",
        description=bundle.get("description"),
        organization=None,
        languages=tuple(n["name"] for n in (bundle.get("languages") or {}).get("nodes", [])),
        topics=tuple(
            n["topic"]["name"] for n in (bundle.get("repositoryTopics") or {}).get("nodes", [])
        ),
        license_spdx=license_info.get("spdxId"),
        stars=bundle.get("stargazerCount") or 0,
        forks=bundle.get("forkCount") or 0,
        archived=bool(bundle.get("isArchived")),
        latest_commit_at=_parse_datetime(target.get("committedDate")),
        latest_release_at=_parse_datetime(latest_release.get("publishedAt")),
        open_issues=(bundle.get("openIssues") or {}).get("totalCount", 0),
        open_pull_requests=(bundle.get("openPullRequests") or {}).get("totalCount", 0),
        recent_merged_prs=merged.get("totalCount", 0),
        recent_external_contributor_prs=external_prs,
        has_contributing_guide=bundle.get("contributing") is not None,
        has_pr_template=bundle.get("prTemplate") is not None,
        has_issue_template=bundle.get("issueTemplateDir") is not None,
        has_security_policy=bundle.get("securityPolicy") is not None,
        discovered_via=discovered_via,
    )


async def discover_repository_candidates(
    rest_client: GitHubRestClient,
    graphql_client: GraphQLClient,
    *,
    min_candidates: int = MIN_CANDIDATES,
    queries: tuple[str, ...] = DISCOVERY_QUERIES,
    enrichment_concurrency: int = 4,
) -> list[RepositoryCandidate]:
    """Search all target domains, deduplicate, and enrich each surviving
    candidate with a single GraphQL request. Logs and skips (rather than
    failing outright) any repository GraphQL can no longer find — GitHub's
    search index can briefly lag deletions/renames."""
    by_full_name, discovered_via = await _search_all_domains(rest_client, queries)

    if len(by_full_name) < min_candidates:
        logger.warning(
            "only found %d candidates across %d domain queries (wanted >= %d)",
            len(by_full_name),
            len(queries),
            min_candidates,
        )

    semaphore = asyncio.Semaphore(enrichment_concurrency)

    async def _enrich(full_name: str) -> RepositoryCandidate | None:
        owner, name = full_name.split("/", 1)
        async with semaphore:
            try:
                bundle = await graphql_client.fetch_repository_bundle(owner, name)
            except GitHubNotFoundError:
                logger.info("skipping %s: no longer found via GraphQL", full_name)
                return None
        return _candidate_from_bundle(
            full_name, bundle, discovered_via=tuple(sorted(discovered_via[full_name]))
        )

    enriched = await asyncio.gather(*(_enrich(fn) for fn in by_full_name))
    return [c for c in enriched if c is not None]
