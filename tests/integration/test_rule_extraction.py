import base64

import httpx
import pytest
import respx

from opensource_scout.github.client import GitHubRestClient
from opensource_scout.repository.rules import extract_contribution_rules

CONTRIBUTING = """# Contributing

Run tests with `pytest -q`. Format with `ruff format .`. Lint with `ruff check .`.
Please sign off your commits (DCO). Use Conventional Commits for messages.
Branch names should start with feat/ or fix/.
"""


def _b64(text: str) -> dict:
    return {"encoding": "base64", "content": base64.b64encode(text.encode()).decode()}


@pytest.mark.respx(base_url="https://api.github.com")
async def test_extracts_test_and_lint_commands_from_contributing(
    respx_mock: respx.MockRouter,
) -> None:
    def contents(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/repos/octo/example/contents/CONTRIBUTING.md":
            return httpx.Response(200, json=_b64(CONTRIBUTING))
        return httpx.Response(404)

    respx_mock.get(url__regex=r".*/repos/octo/example/contents/.*").mock(side_effect=contents)

    client = GitHubRestClient(token="t")
    try:
        rules = await extract_contribution_rules(client, "octo", "example")
    finally:
        await client.aclose()

    categories = {r.category for r in rules}
    assert "test_command" in categories
    assert "lint_command" in categories
    assert "dco_or_cla" in categories
    assert "commit_convention" in categories
    assert "branch_rules" in categories
    for rule in rules:
        assert rule.file_path == "CONTRIBUTING.md"
        assert 0.0 <= rule.confidence <= 1.0
        assert rule.excerpt  # every rule carries its supporting evidence


@pytest.mark.respx(base_url="https://api.github.com")
async def test_missing_files_are_skipped_without_error(respx_mock: respx.MockRouter) -> None:
    respx_mock.get(url__regex=r".*/repos/octo/bare/contents/.*").mock(
        return_value=httpx.Response(404)
    )
    client = GitHubRestClient(token="t")
    try:
        rules = await extract_contribution_rules(client, "octo", "bare")
    finally:
        await client.aclose()
    assert rules == []


@pytest.mark.respx(base_url="https://api.github.com")
async def test_presence_only_files_produce_high_confidence_rules(
    respx_mock: respx.MockRouter,
) -> None:
    def contents(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/repos/octo/example/contents/LICENSE":
            return httpx.Response(200, json=_b64("MIT License"))
        return httpx.Response(404)

    respx_mock.get(url__regex=r".*/repos/octo/example/contents/.*").mock(side_effect=contents)
    client = GitHubRestClient(token="t")
    try:
        rules = await extract_contribution_rules(client, "octo", "example")
    finally:
        await client.aclose()

    license_rules = [r for r in rules if r.category == "license_present"]
    assert len(license_rules) == 1
    assert license_rules[0].confidence == 1.0
