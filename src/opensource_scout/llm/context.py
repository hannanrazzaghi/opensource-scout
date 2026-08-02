"""Deterministic repository-context selection.

Ranks candidate files by lexical overlap with a set of query terms (issue
title/body keywords, symbol names, whatever the caller derives) and selects
a bounded, token-budgeted subset — never an unfiltered repository dump. This
is intentionally simple lexical scoring, not a BM25 or embedding index:
good enough to keep an LLM call's input small and explainable, which is the
actual requirement (see docs/architecture.md's context-construction rules).
"""

from __future__ import annotations

import re

from opensource_scout.domain.context import ContextBundle, ContextFile

_WORD_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")
_CHARS_PER_TOKEN_ESTIMATE = 4


def _tokenize(text: str) -> set[str]:
    return {m.group(0).lower() for m in _WORD_PATTERN.finditer(text)}


def _score(content: str, query_terms: set[str]) -> float:
    if not query_terms:
        return 0.0
    file_tokens = _tokenize(content)
    return len(file_tokens & query_terms) / len(query_terms)


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // _CHARS_PER_TOKEN_ESTIMATE)


def build_context_bundle(
    base_commit_sha: str,
    files: dict[str, str],
    query_terms: list[str],
    *,
    max_files: int = 8,
    max_tokens: int = 8000,
) -> ContextBundle:
    """Select up to ``max_files`` files, ranked by lexical overlap with
    ``query_terms``, without exceeding ``max_tokens`` of estimated content.

    Files with zero overlap are never selected, even if there's budget left
    — an irrelevant file padding out the token count isn't useful context.
    """
    terms = {t.lower() for t in query_terms if t.strip()}
    scored = sorted(
        ((path, content, _score(content, terms)) for path, content in files.items()),
        key=lambda item: item[2],
        reverse=True,
    )

    selected: list[ContextFile] = []
    excluded: list[str] = []
    total_tokens = 0

    for path, content, score in scored:
        if score <= 0:
            if path not in [f.path for f in selected]:
                excluded.append(path)
            continue
        if len(selected) >= max_files:
            excluded.append(path)
            continue
        file_tokens = _estimate_tokens(content)
        if total_tokens + file_tokens > max_tokens:
            excluded.append(path)
            continue
        selected.append(
            ContextFile(
                path=path,
                content=content,
                score=round(score, 4),
                selection_reason=f"lexical overlap with {len(terms)} query term(s)",
            )
        )
        total_tokens += file_tokens

    relevant_tests = tuple(f.path for f in selected if "test" in f.path.lower())

    return ContextBundle(
        base_commit_sha=base_commit_sha,
        selected_files=tuple(selected),
        excluded_files=tuple(excluded),
        relevant_tests=relevant_tests,
        approx_token_count=total_tokens,
    )
