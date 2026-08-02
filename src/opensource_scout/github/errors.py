"""Typed errors for the GitHub client. Callers branch on these instead of
inspecting HTTP status codes, so degraded/offline behavior stays explicit."""

from __future__ import annotations


class GitHubError(Exception):
    """Base class for all GitHub client errors."""


class GitHubNotFoundError(GitHubError):
    """404 — the resource does not exist or is not visible to this token."""


class GitHubAuthError(GitHubError):
    """401/403 (not rate-limit related) — missing or invalid credentials."""


class GitHubRateLimitedError(GitHubError):
    """403/429 due to primary or secondary rate limiting.

    Carries ``retry_after`` (seconds) when the server provided one, so
    callers can decide whether to wait or fail fast in offline/degraded mode.
    """

    def __init__(self, message: str, *, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class GitHubServerError(GitHubError):
    """5xx — retryable server-side failure."""
