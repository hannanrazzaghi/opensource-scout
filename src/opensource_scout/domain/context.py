"""Domain models for deterministic repository-context bundles.

See :mod:`opensource_scout.llm.context` for how these are built. Kept
separate from :mod:`opensource_scout.domain.models` because these are purely
an LLM-input concern, not part of the persisted contribution/scoring domain.
"""

from __future__ import annotations

from pydantic import BaseModel


class ContextFile(BaseModel):
    path: str
    content: str
    score: float
    selection_reason: str


class ContextBundle(BaseModel):
    """A deterministically-selected, bounded slice of a repository — never
    a full repository dump — ready to hand to an LLM call."""

    base_commit_sha: str
    selected_files: tuple[ContextFile, ...]
    excluded_files: tuple[str, ...]
    relevant_tests: tuple[str, ...]
    approx_token_count: int
