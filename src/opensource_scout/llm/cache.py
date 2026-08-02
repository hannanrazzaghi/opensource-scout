"""Prompt-hash cache for structured LLM outputs.

Keyed on a hash of (model, task category, prompt) so an identical request —
same file content, same commit SHA, same issue state — is served from
SQLite instead of re-billed. Cache invalidation is implicit: callers are
responsible for including whatever varies (commit SHA, issue
``updated_at``, file content hash) in the prompt they hash, per the
project's caching rules in docs/architecture.md.
"""

from __future__ import annotations

import hashlib
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from opensource_scout.db.models import LlmCacheRow


def compute_cache_key(model: str, task_category: str, prompt: str) -> str:
    digest = hashlib.sha256(f"{model}\x00{task_category}\x00{prompt}".encode()).hexdigest()
    return digest


class LlmCache(Protocol):
    def get(self, cache_key: str) -> dict[str, Any] | None: ...

    def set(self, cache_key: str, *, model: str, response: dict[str, Any]) -> None: ...


class InMemoryLlmCache:
    def __init__(self) -> None:
        self._store: dict[str, dict[str, Any]] = {}

    def get(self, cache_key: str) -> dict[str, Any] | None:
        return self._store.get(cache_key)

    def set(self, cache_key: str, *, model: str, response: dict[str, Any]) -> None:
        self._store[cache_key] = response


class SqlAlchemyLlmCache:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def get(self, cache_key: str) -> dict[str, Any] | None:
        with self._session_factory() as session:
            row = session.execute(
                select(LlmCacheRow).where(LlmCacheRow.cache_key == cache_key)
            ).scalar_one_or_none()
            return row.response_json if row is not None else None

    def set(self, cache_key: str, *, model: str, response: dict[str, Any]) -> None:
        with self._session_factory() as session:
            row = session.execute(
                select(LlmCacheRow).where(LlmCacheRow.cache_key == cache_key)
            ).scalar_one_or_none()
            if row is None:
                row = LlmCacheRow(cache_key=cache_key, model=model, response_json=response)
                session.add(row)
            else:
                row.response_json = response
            session.commit()
