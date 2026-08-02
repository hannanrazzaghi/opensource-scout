"""Contribution-rule extraction: read a repository's own documented
process (CONTRIBUTING, PR/issue templates, tooling config) into structured,
evidenced rules instead of relying on a summary an LLM might hallucinate.

Every extracted :class:`~opensource_scout.domain.models.ContributionRule`
carries the file it came from, a heading or line range, a confidence score,
and the exact excerpt that justified it — the same evidence-over-trust
principle used throughout scoring.
"""

from __future__ import annotations

import base64
import re
from dataclasses import dataclass

from opensource_scout.domain.models import ContributionRule
from opensource_scout.github.client import GitHubRestClient
from opensource_scout.github.errors import GitHubNotFoundError
from opensource_scout.logging import get_logger

logger = get_logger("repository.rules")

# Candidate paths, in priority order, for each category of interest. Only
# the first match per category is used — most repositories only have one.
_CANDIDATE_FILES: tuple[str, ...] = (
    "CONTRIBUTING.md",
    "CONTRIBUTING.rst",
    "docs/CONTRIBUTING.md",
    "SECURITY.md",
    "CODE_OF_CONDUCT.md",
    ".github/pull_request_template.md",
    "pyproject.toml",
    "tox.ini",
    "noxfile.py",
    "Makefile",
    "justfile",
    "Cargo.toml",
    "package.json",
    ".pre-commit-config.yaml",
)

_COMMAND_PATTERNS: tuple[tuple[str, str, re.Pattern[str]], ...] = (
    ("test_command", "pytest invocation", re.compile(r"^\s*.*\bpytest\b.*$", re.MULTILINE)),
    ("test_command", "cargo test invocation", re.compile(r"^\s*.*\bcargo test\b.*$", re.MULTILINE)),
    (
        "test_command",
        "npm/yarn test invocation",
        re.compile(r"^\s*.*\b(npm|yarn) test\b.*$", re.MULTILINE),
    ),
    ("lint_command", "ruff invocation", re.compile(r"^\s*.*\bruff\b.*$", re.MULTILINE)),
    ("lint_command", "eslint invocation", re.compile(r"^\s*.*\beslint\b.*$", re.MULTILINE)),
    (
        "format_command",
        "black/prettier invocation",
        re.compile(r"^\s*.*\b(black|prettier)\b.*$", re.MULTILINE),
    ),
    (
        "typecheck_command",
        "mypy/pyright invocation",
        re.compile(r"^\s*.*\b(mypy|pyright)\b.*$", re.MULTILINE),
    ),
    (
        "build_command",
        "make build invocation",
        re.compile(r"^\s*.*\bmake\s+build\b.*$", re.MULTILINE),
    ),
)

_TEXT_RULE_PATTERNS: tuple[tuple[str, str, re.Pattern[str]], ...] = (
    (
        "dco_or_cla",
        "Signed-off-by / DCO requirement",
        re.compile(r"(?im)^.*\b(sign[- ]off|DCO|signed-off-by)\b.*$"),
    ),
    (
        "dco_or_cla",
        "CLA requirement",
        re.compile(r"(?im)^.*\bcontributor license agreement\b.*$"),
    ),
    (
        "commit_convention",
        "Conventional Commits requirement",
        re.compile(r"(?im)^.*\bconventional commits?\b.*$"),
    ),
    (
        "branch_rules",
        "branch naming/workflow rule",
        re.compile(r"(?im)^.*\bbranch(es)?\b.*\b(name|names|naming|prefix|from main)\b.*$"),
    ),
    (
        "pr_title_rule",
        "PR title convention",
        re.compile(r"(?im)^.*\bpull request\b.*\btitle\b.*$"),
    ),
    (
        "design_discussion",
        "design discussion / RFC requirement",
        re.compile(r"(?im)^.*\b(rfc|design doc|discuss(ed)? .* before)\b.*$"),
    ),
    (
        "changelog_requirement",
        "changelog update requirement",
        re.compile(r"(?im)^.*\bCHANGELOG\b.*\b(update|add|entry)\b.*$"),
    ),
)

_PRESENCE_ONLY_FILES: tuple[tuple[str, str], ...] = (
    ("LICENSE", "license_present"),
    ("SECURITY.md", "security_reporting"),
    ("CODE_OF_CONDUCT.md", "code_of_conduct"),
    (".github/pull_request_template.md", "pr_template_present"),
)


@dataclass(frozen=True)
class _FetchedFile:
    path: str
    text: str


async def _fetch_file(
    client: GitHubRestClient, owner: str, name: str, path: str
) -> _FetchedFile | None:
    try:
        payload = await client.get_json(f"/repos/{owner}/{name}/contents/{path}")
    except GitHubNotFoundError:
        return None
    if not isinstance(payload, dict) or payload.get("encoding") != "base64":
        return None
    try:
        text = base64.b64decode(payload["content"]).decode("utf-8", errors="replace")
    except (KeyError, ValueError):
        return None
    return _FetchedFile(path=path, text=text)


async def _path_exists(client: GitHubRestClient, owner: str, name: str, path: str) -> bool:
    """Check whether a file or directory exists, without assuming the
    response shape — a directory listing is a JSON array, a file is an
    object; either counts as "present"."""
    try:
        await client.get_json(f"/repos/{owner}/{name}/contents/{path}")
    except GitHubNotFoundError:
        return False
    return True


def _extract_from_text(
    repository_full_name: str, file_path: str, text: str
) -> list[ContributionRule]:
    rules: list[ContributionRule] = []
    for category, label, pattern in (*_COMMAND_PATTERNS, *_TEXT_RULE_PATTERNS):
        match = pattern.search(text)
        if not match:
            continue
        excerpt = match.group(0).strip()[:200]
        line_number = text.count("\n", 0, match.start()) + 1
        rules.append(
            ContributionRule(
                repository_full_name=repository_full_name,
                category=category,
                file_path=file_path,
                heading_or_range=f"line {line_number} ({label})",
                confidence=0.7,
                excerpt=excerpt,
            )
        )
    return rules


async def extract_contribution_rules(
    client: GitHubRestClient, owner: str, name: str
) -> list[ContributionRule]:
    """Fetch known contribution-relevant files and extract structured,
    evidenced rules. Missing files are silently skipped — most repositories
    only have a subset of the candidate files."""
    repository_full_name = f"{owner}/{name}"
    rules: list[ContributionRule] = []

    for path in _CANDIDATE_FILES:
        fetched = await _fetch_file(client, owner, name, path)
        if fetched is None:
            continue
        rules.extend(_extract_from_text(repository_full_name, fetched.path, fetched.text))

    for path, category in _PRESENCE_ONLY_FILES:
        fetched = await _fetch_file(client, owner, name, path)
        if fetched is None:
            continue
        rules.append(
            ContributionRule(
                repository_full_name=repository_full_name,
                category=category,
                file_path=path,
                heading_or_range="file present",
                confidence=1.0,
                excerpt=fetched.text[:200].strip(),
            )
        )

    if await _path_exists(client, owner, name, ".github/ISSUE_TEMPLATE"):
        rules.append(
            ContributionRule(
                repository_full_name=repository_full_name,
                category="issue_template_present",
                file_path=".github/ISSUE_TEMPLATE",
                heading_or_range="directory present",
                confidence=0.9,
                excerpt="",
            )
        )

    logger.info("extracted %d contribution rules for %s", len(rules), repository_full_name)
    return rules
