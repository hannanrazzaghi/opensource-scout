import httpx
import pytest
import respx

from opensource_scout.github.client import GitHubRestClient
from opensource_scout.github.discovery import discover_repository_candidates
from opensource_scout.github.errors import GitHubNotFoundError
from opensource_scout.github.graphql import GRAPHQL_URL, GraphQLClient

_BUNDLE = {
    "nameWithOwner": "octo/example",
    "url": "https://github.com/octo/example",
    "description": "A retrieval engine",
    "isArchived": False,
    "stargazerCount": 100,
    "forkCount": 10,
    "licenseInfo": {"spdxId": "MIT"},
    "languages": {"nodes": [{"name": "Python"}]},
    "repositoryTopics": {"nodes": [{"topic": {"name": "retrieval"}}]},
    "defaultBranchRef": {"target": {"committedDate": "2026-07-01T00:00:00Z"}},
    "latestRelease": None,
    "openIssues": {"totalCount": 5},
    "openPullRequests": {"totalCount": 1},
    "recentMergedPullRequests": {
        "totalCount": 3,
        "nodes": [
            {"authorAssociation": "CONTRIBUTOR"},
            {"authorAssociation": "OWNER"},
        ],
    },
    "contributing": {"id": "x"},
    "prTemplate": None,
    "issueTemplateDir": None,
    "securityPolicy": None,
}


@pytest.mark.respx(base_url="https://api.github.com")
async def test_discovery_dedupes_across_domain_queries(respx_mock: respx.MockRouter) -> None:
    # Every search query "finds" the same single repository, exercising
    # deduplication and discovered_via aggregation across queries.
    respx_mock.get(url__regex=r".*/search/repositories.*").mock(
        return_value=httpx.Response(200, json=[{"full_name": "octo/example"}])
    )
    respx_mock.post(GRAPHQL_URL).mock(
        return_value=httpx.Response(200, json={"data": {"repository": _BUNDLE}})
    )

    rest_client = GitHubRestClient(token="t")
    graphql_client = GraphQLClient(token="t")
    try:
        candidates = await discover_repository_candidates(
            rest_client, graphql_client, min_candidates=1
        )
    finally:
        await rest_client.aclose()
        await graphql_client.aclose()

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.full_name == "octo/example"
    assert candidate.stars == 100
    assert candidate.recent_external_contributor_prs == 1  # only the CONTRIBUTOR node counts
    assert len(candidate.discovered_via) > 1  # surfaced by more than one query


@pytest.mark.respx(base_url="https://api.github.com")
async def test_discovery_skips_repositories_graphql_can_no_longer_find(
    respx_mock: respx.MockRouter,
) -> None:
    respx_mock.get(url__regex=r".*/search/repositories.*").mock(
        return_value=httpx.Response(200, json=[{"full_name": "octo/vanished"}])
    )
    respx_mock.post(GRAPHQL_URL).mock(
        return_value=httpx.Response(
            200, json={"data": {"repository": None}, "errors": [{"type": "NOT_FOUND"}]}
        )
    )

    rest_client = GitHubRestClient(token="t")
    graphql_client = GraphQLClient(token="t")
    try:
        candidates = await discover_repository_candidates(
            rest_client, graphql_client, min_candidates=1
        )
    finally:
        await rest_client.aclose()
        await graphql_client.aclose()

    assert candidates == []


async def test_graphql_not_found_error_is_typed() -> None:
    import respx as respx_module

    with respx_module.mock() as router:
        router.post(GRAPHQL_URL).mock(
            return_value=httpx.Response(
                200, json={"data": {"repository": None}, "errors": [{"type": "NOT_FOUND"}]}
            )
        )
        client = GraphQLClient(token="t")
        try:
            with pytest.raises(GitHubNotFoundError):
                await client.fetch_repository_bundle("octo", "missing")
        finally:
            await client.aclose()
