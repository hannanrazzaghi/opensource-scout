"""Async GitHub REST client: pagination, rate-limit tracking, conditional
(ETag) caching, retry with backoff, and bounded concurrency.

Kept as a single concrete class rather than split behind a formal
``Protocol`` — tests substitute a real :class:`httpx.AsyncClient` wired to a
mock transport (via ``respx``) rather than a fake implementation of this
class, so the class itself *is* the seam tests replace the transport under.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from types import TracebackType
from typing import Any, Self

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from opensource_scout.github.cache import HttpCache, InMemoryHttpCache
from opensource_scout.github.errors import (
    GitHubAuthError,
    GitHubError,
    GitHubNotFoundError,
    GitHubRateLimitedError,
    GitHubServerError,
)
from opensource_scout.github.rate_limit import RateLimitState, retry_after_from_headers
from opensource_scout.logging import get_logger

logger = get_logger("github.client")

DEFAULT_BASE_URL = "https://api.github.com"
_RETRYABLE = (GitHubServerError, GitHubRateLimitedError, httpx.TransportError)


class GitHubRestClient:
    def __init__(
        self,
        *,
        token: str | None = None,
        base_url: str = DEFAULT_BASE_URL,
        concurrency: int = 4,
        cache: HttpCache | None = None,
        http_client: httpx.AsyncClient | None = None,
        timeout: float = 30.0,
    ) -> None:
        headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self._owns_client = http_client is None
        self._client = http_client or httpx.AsyncClient(
            base_url=base_url, headers=headers, timeout=timeout
        )
        self._semaphore = asyncio.Semaphore(concurrency)
        self._cache = cache or InMemoryHttpCache()
        self.rate_limit = RateLimitState()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    @retry(
        retry=retry_if_exception_type(_RETRYABLE),
        wait=wait_exponential(multiplier=1, min=1, max=30),
        stop=stop_after_attempt(5),
        reraise=True,
    )
    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        async with self._semaphore:
            if self.rate_limit.should_wait():
                delay = self.rate_limit.seconds_until_reset()
                logger.info("rate limit budget low; sleeping %.1fs before next request", delay)
                await asyncio.sleep(delay)
            response = await self._client.request(method, path, **kwargs)

        self.rate_limit.update_from_headers(response.headers)
        _raise_for_status(response)
        return response

    async def get_json(self, path: str, *, params: dict[str, Any] | None = None) -> Any:
        """A single GET, honoring a cached ETag via ``If-None-Match``. A 304
        response returns the previously cached body without counting against
        the abuse-detection budget as heavily as a full response would."""
        cache_key = _cache_key(path, params)
        cached = self._cache.get(cache_key)
        headers = {"If-None-Match": cached.etag} if cached and cached.etag else {}

        response = await self._request("GET", path, params=params, headers=headers)

        if response.status_code == 304 and cached is not None:
            return cached.body

        body = response.json()
        etag = response.headers.get("etag")
        if etag:
            self._cache.set(cache_key, etag=etag, body=body, status_code=response.status_code)
        return body

    async def post_json(self, path: str, *, json_body: dict[str, Any]) -> Any:
        """A single POST (e.g. creating a pull request). Never used for
        discovery — only for the approval-gated external mutation commands
        in :mod:`opensource_scout.reports.contribution_report`."""
        response = await self._request("POST", path, json=json_body)
        return response.json()

    async def paginate(
        self, path: str, *, params: dict[str, Any] | None = None, per_page: int = 100
    ) -> AsyncIterator[Any]:
        """Yield every item across all pages of a list endpoint, following
        the ``Link: rel="next"`` header rather than assuming a page count."""
        query = dict(params or {})
        query.setdefault("per_page", per_page)
        next_url: str | None = path
        next_params: dict[str, Any] | None = query

        while next_url is not None:
            response = await self._request("GET", next_url, params=next_params)
            for item in response.json():
                yield item
            next_url = response.links.get("next", {}).get("url")
            next_params = None  # the next URL already encodes all query params


def _cache_key(path: str, params: dict[str, Any] | None) -> str:
    if not params:
        return path
    encoded = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
    return f"{path}?{encoded}"


def _raise_for_status(response: httpx.Response) -> None:
    if response.status_code < 400:
        return

    if response.status_code == 404:
        raise GitHubNotFoundError(f"not found: {response.request.url}")

    if response.status_code in (403, 429):
        remaining = response.headers.get("x-ratelimit-remaining")
        if remaining == "0" or response.status_code == 429:
            raise GitHubRateLimitedError(
                f"rate limited: {response.request.url}",
                retry_after=retry_after_from_headers(response.headers),
            )
        raise GitHubAuthError(f"forbidden: {response.request.url}")

    if response.status_code == 401:
        raise GitHubAuthError(f"unauthorized: {response.request.url}")

    if response.status_code >= 500:
        raise GitHubServerError(f"server error {response.status_code}: {response.request.url}")

    raise GitHubError(f"unexpected status {response.status_code}: {response.request.url}")
