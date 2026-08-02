import httpx
import pytest
import respx

from opensource_scout.github.client import GitHubRestClient
from opensource_scout.github.graphql import GRAPHQL_URL, GraphQLClient
from opensource_scout.github.issues import discover_issues


def _bundle(**overrides: object) -> dict:
    base = {
        "title": "Example issue",
        "url": "https://github.com/octo/example/issues/1",
        "body": "x" * 60,
        "createdAt": "2026-01-01T00:00:00Z",
        "updatedAt": "2026-01-02T00:00:00Z",
        "labels": {"nodes": []},
        "assignees": {"nodes": []},
        "comments": {"totalCount": 0},
        "timelineItems": {"nodes": []},
    }
    base.update(overrides)
    return base


@pytest.mark.respx(base_url="https://api.github.com")
async def test_pull_requests_are_excluded_from_issue_list(respx_mock: respx.MockRouter) -> None:
    respx_mock.get(url__regex=r".*/repos/octo/example/issues.*").mock(
        return_value=httpx.Response(
            200,
            json=[
                {"number": 1},
                {"number": 2, "pull_request": {"url": "https://api.github.com/x"}},
            ],
        )
    )
    respx_mock.post(GRAPHQL_URL).mock(
        return_value=httpx.Response(200, json={"data": {"repository": {"issue": _bundle()}}})
    )

    rest_client = GitHubRestClient(token="t")
    graphql_client = GraphQLClient(token="t")
    try:
        issues = await discover_issues(rest_client, graphql_client, "octo", "example")
    finally:
        await rest_client.aclose()
        await graphql_client.aclose()

    assert len(issues) == 1
    assert issues[0].number == 1


@pytest.mark.respx(base_url="https://api.github.com")
async def test_open_cross_referenced_pr_marks_competing_work(
    respx_mock: respx.MockRouter,
) -> None:
    respx_mock.get(url__regex=r".*/repos/octo/example/issues.*").mock(
        return_value=httpx.Response(200, json=[{"number": 1}])
    )
    bundle = _bundle(
        timelineItems={"nodes": [{"source": {"number": 9, "state": "OPEN"}}]},
    )
    respx_mock.post(GRAPHQL_URL).mock(
        return_value=httpx.Response(200, json={"data": {"repository": {"issue": bundle}}})
    )

    rest_client = GitHubRestClient(token="t")
    graphql_client = GraphQLClient(token="t")
    try:
        issues = await discover_issues(rest_client, graphql_client, "octo", "example")
    finally:
        await rest_client.aclose()
        await graphql_client.aclose()

    assert issues[0].has_competing_pull_request is True
    assert issues[0].linked_pull_requests == ("9",)


@pytest.mark.respx(base_url="https://api.github.com")
async def test_closed_cross_referenced_pr_does_not_mark_competing_work(
    respx_mock: respx.MockRouter,
) -> None:
    respx_mock.get(url__regex=r".*/repos/octo/example/issues.*").mock(
        return_value=httpx.Response(200, json=[{"number": 1}])
    )
    bundle = _bundle(
        timelineItems={"nodes": [{"source": {"number": 9, "state": "MERGED"}}]},
    )
    respx_mock.post(GRAPHQL_URL).mock(
        return_value=httpx.Response(200, json={"data": {"repository": {"issue": bundle}}})
    )

    rest_client = GitHubRestClient(token="t")
    graphql_client = GraphQLClient(token="t")
    try:
        issues = await discover_issues(rest_client, graphql_client, "octo", "example")
    finally:
        await rest_client.aclose()
        await graphql_client.aclose()

    assert issues[0].has_competing_pull_request is False


@pytest.mark.respx(base_url="https://api.github.com")
async def test_assignees_set_has_active_assignee(respx_mock: respx.MockRouter) -> None:
    respx_mock.get(url__regex=r".*/repos/octo/example/issues.*").mock(
        return_value=httpx.Response(200, json=[{"number": 1}])
    )
    bundle = _bundle(assignees={"nodes": [{"login": "alice"}]})
    respx_mock.post(GRAPHQL_URL).mock(
        return_value=httpx.Response(200, json={"data": {"repository": {"issue": bundle}}})
    )

    rest_client = GitHubRestClient(token="t")
    graphql_client = GraphQLClient(token="t")
    try:
        issues = await discover_issues(rest_client, graphql_client, "octo", "example")
    finally:
        await rest_client.aclose()
        await graphql_client.aclose()

    assert issues[0].has_active_assignee is True
    assert issues[0].assignees == ("alice",)
