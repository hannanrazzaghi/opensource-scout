import asyncio

import httpx
import pytest
import respx

from opensource_scout.github.cache import InMemoryHttpCache
from opensource_scout.github.client import GitHubRestClient
from opensource_scout.github.errors import (
    GitHubAuthError,
    GitHubNotFoundError,
    GitHubRateLimitedError,
)


@pytest.fixture(autouse=True)
def _fast_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tenacity/rate-limit backoff use real asyncio.sleep; patch it to a
    no-op so retry/backoff tests run instantly instead of waiting seconds."""

    async def _noop_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr(asyncio, "sleep", _noop_sleep)


@pytest.mark.respx(base_url="https://api.github.com")
async def test_get_json_returns_body(respx_mock: respx.MockRouter) -> None:
    respx_mock.get("/repos/octo/example").mock(
        return_value=httpx.Response(200, json={"name": "example"})
    )
    client = GitHubRestClient(token="t")
    try:
        body = await client.get_json("/repos/octo/example")
    finally:
        await client.aclose()
    assert body == {"name": "example"}


@pytest.mark.respx(base_url="https://api.github.com")
async def test_pagination_follows_link_header_across_multiple_pages(
    respx_mock: respx.MockRouter,
) -> None:
    page1 = httpx.Response(
        200,
        json=[{"id": 1}, {"id": 2}],
        headers={"link": '<https://api.github.com/search/repositories?page=2>; rel="next"'},
    )
    page2 = httpx.Response(
        200,
        json=[{"id": 3}],
        headers={"link": '<https://api.github.com/search/repositories?page=3>; rel="next"'},
    )
    page3 = httpx.Response(200, json=[{"id": 4}])
    respx_mock.get("/search/repositories").mock(side_effect=[page1, page2, page3])

    client = GitHubRestClient(token="t")
    try:
        items = [item async for item in client.paginate("/search/repositories")]
    finally:
        await client.aclose()

    assert [i["id"] for i in items] == [1, 2, 3, 4]


@pytest.mark.respx(base_url="https://api.github.com")
async def test_etag_cache_hit_returns_cached_body_on_304(respx_mock: respx.MockRouter) -> None:
    first = httpx.Response(200, json={"v": 1}, headers={"etag": '"abc123"'})
    second = httpx.Response(304, headers={"etag": '"abc123"'})
    respx_mock.get("/repos/octo/example").mock(side_effect=[first, second])

    cache = InMemoryHttpCache()
    client = GitHubRestClient(token="t", cache=cache)
    try:
        first_body = await client.get_json("/repos/octo/example")
        second_body = await client.get_json("/repos/octo/example")
    finally:
        await client.aclose()

    assert first_body == {"v": 1}
    assert second_body == {"v": 1}  # served from cache on 304, not re-fetched


@pytest.mark.respx(base_url="https://api.github.com")
async def test_second_request_sends_if_none_match_header(respx_mock: respx.MockRouter) -> None:
    respx_mock.get("/repos/octo/example").mock(
        side_effect=[
            httpx.Response(200, json={"v": 1}, headers={"etag": '"abc123"'}),
            httpx.Response(304, headers={"etag": '"abc123"'}),
        ]
    )
    client = GitHubRestClient(token="t")
    try:
        await client.get_json("/repos/octo/example")
        await client.get_json("/repos/octo/example")
    finally:
        await client.aclose()

    second_request = respx_mock.calls[1].request
    assert second_request.headers["if-none-match"] == '"abc123"'


@pytest.mark.respx(base_url="https://api.github.com")
async def test_server_error_is_retried_then_succeeds(respx_mock: respx.MockRouter) -> None:
    respx_mock.get("/repos/octo/example").mock(
        side_effect=[
            httpx.Response(500),
            httpx.Response(500),
            httpx.Response(200, json={"ok": True}),
        ]
    )
    client = GitHubRestClient(token="t")
    try:
        body = await client.get_json("/repos/octo/example")
    finally:
        await client.aclose()

    assert body == {"ok": True}
    assert respx_mock.calls.call_count == 3


@pytest.mark.respx(base_url="https://api.github.com")
async def test_rate_limited_response_raises_after_exhausting_retries(
    respx_mock: respx.MockRouter,
) -> None:
    respx_mock.get("/repos/octo/example").mock(
        return_value=httpx.Response(
            403,
            headers={"x-ratelimit-remaining": "0", "retry-after": "1"},
        )
    )
    client = GitHubRestClient(token="t")
    try:
        with pytest.raises(GitHubRateLimitedError):
            await client.get_json("/repos/octo/example")
    finally:
        await client.aclose()


@pytest.mark.respx(base_url="https://api.github.com")
async def test_low_remaining_budget_sleeps_before_next_request(
    respx_mock: respx.MockRouter, monkeypatch: pytest.MonkeyPatch
) -> None:
    respx_mock.get("/repos/octo/a").mock(
        return_value=httpx.Response(
            200,
            json={},
            headers={"x-ratelimit-remaining": "1", "x-ratelimit-reset": "9999999999"},
        )
    )
    respx_mock.get("/repos/octo/b").mock(return_value=httpx.Response(200, json={}))

    sleep_calls: list[float] = []

    async def _tracking_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)

    monkeypatch.setattr(asyncio, "sleep", _tracking_sleep)

    client = GitHubRestClient(token="t")
    try:
        await client.get_json("/repos/octo/a")
        await client.get_json("/repos/octo/b")
    finally:
        await client.aclose()

    assert len(sleep_calls) >= 1


@pytest.mark.respx(base_url="https://api.github.com")
async def test_404_raises_not_found_without_retry(respx_mock: respx.MockRouter) -> None:
    route = respx_mock.get("/repos/octo/missing").mock(return_value=httpx.Response(404))
    client = GitHubRestClient(token="t")
    try:
        with pytest.raises(GitHubNotFoundError):
            await client.get_json("/repos/octo/missing")
    finally:
        await client.aclose()
    assert route.call_count == 1  # 404 is not retryable


@pytest.mark.respx(base_url="https://api.github.com")
async def test_401_raises_auth_error(respx_mock: respx.MockRouter) -> None:
    respx_mock.get("/repos/octo/example").mock(return_value=httpx.Response(401))
    client = GitHubRestClient(token="bad")
    try:
        with pytest.raises(GitHubAuthError):
            await client.get_json("/repos/octo/example")
    finally:
        await client.aclose()
