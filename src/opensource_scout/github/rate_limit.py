"""Tracking and pre-emptive backoff for GitHub's rate-limit headers.

Reading ``X-RateLimit-Remaining``/``X-RateLimit-Reset`` after every response
and sleeping *before* the next request when the budget is nearly exhausted is
cheaper and more predictable than reacting to a 403 after the fact.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import httpx

# Sleep pre-emptively once fewer than this many requests remain in the
# current window, rather than waiting to be rejected.
LOW_REMAINING_THRESHOLD = 2


@dataclass
class RateLimitState:
    limit: int | None = None
    remaining: int | None = None
    reset_at: float | None = None  # unix timestamp

    def update_from_headers(self, headers: httpx.Headers) -> None:
        limit = headers.get("x-ratelimit-limit")
        remaining = headers.get("x-ratelimit-remaining")
        reset = headers.get("x-ratelimit-reset")
        if limit is not None:
            self.limit = int(limit)
        if remaining is not None:
            self.remaining = int(remaining)
        if reset is not None:
            self.reset_at = float(reset)

    def seconds_until_reset(self, *, now: float | None = None) -> float:
        if self.reset_at is None:
            return 0.0
        return max(0.0, self.reset_at - (now if now is not None else time.time()))

    def should_wait(self) -> bool:
        return self.remaining is not None and self.remaining < LOW_REMAINING_THRESHOLD


def retry_after_from_headers(headers: httpx.Headers) -> float | None:
    value = headers.get("retry-after")
    if value is None:
        return None
    try:
        return float(value)
    except ValueError:
        return None
