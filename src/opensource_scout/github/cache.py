"""Conditional-request (ETag) caching for the GitHub client.

Behind a small :class:`HttpCache` interface so tests can use
:class:`InMemoryHttpCache` instead of talking to SQLite.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from opensource_scout.db.models import HttpCacheRow


@dataclass
class CachedResponse:
    etag: str | None
    body: Any
    status_code: int


class HttpCache(Protocol):
    def get(self, request_key: str) -> CachedResponse | None: ...

    def set(self, request_key: str, *, etag: str | None, body: Any, status_code: int) -> None: ...


class InMemoryHttpCache:
    """Process-local cache; used in tests and as a default when no
    persistent session factory is configured."""

    def __init__(self) -> None:
        self._store: dict[str, CachedResponse] = {}

    def get(self, request_key: str) -> CachedResponse | None:
        return self._store.get(request_key)

    def set(self, request_key: str, *, etag: str | None, body: Any, status_code: int) -> None:
        self._store[request_key] = CachedResponse(etag=etag, body=body, status_code=status_code)


class SqlAlchemyHttpCache:
    """Persists the cache to the ``http_cache`` table so it survives
    process restarts."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def get(self, request_key: str) -> CachedResponse | None:
        with self._session_factory() as session:
            row = session.execute(
                select(HttpCacheRow).where(HttpCacheRow.request_key == request_key)
            ).scalar_one_or_none()
            if row is None:
                return None
            return CachedResponse(etag=row.etag, body=row.body_json, status_code=row.status_code)

    def set(self, request_key: str, *, etag: str | None, body: Any, status_code: int) -> None:
        with self._session_factory() as session:
            row = session.execute(
                select(HttpCacheRow).where(HttpCacheRow.request_key == request_key)
            ).scalar_one_or_none()
            if row is None:
                row = HttpCacheRow(request_key=request_key)
                session.add(row)
            row.etag = etag
            row.body_json = body
            row.status_code = status_code
            session.commit()
