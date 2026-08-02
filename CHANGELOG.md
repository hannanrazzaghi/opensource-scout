# Changelog

All notable changes to this project are documented here. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

## [0.3.0] - Issue intelligence

### Added

- Issue discovery for a selected repository: label-filtered plus a recent-unlabeled sweep, excluding pull requests, enriched via GraphQL with assignees, comment counts, and cross-referenced pull requests.
- Competing-work detection — an issue is flagged when it has an active assignee or an open pull request already references it.
- Repository contribution-rule extraction: fetches CONTRIBUTING/SECURITY/LICENSE/PR-template/tooling-config files and extracts structured, evidenced rules (test/lint/format/typecheck commands, DCO/CLA, commit conventions, branch rules).
- Deterministic issue scoring (career relevance, scope clarity, acceptance probability, technical value, testability, schedule fit) with explicit, evidenced rejection reasons — no LLM.
- `oss discover issues`, `oss issues list`, `oss issue inspect`, `oss issue select`.

## [0.2.0] - GitHub discovery

### Added

- Async GitHub REST client with pagination, rate-limit tracking, ETag-based
  conditional caching, and Tenacity retry/backoff.
- GraphQL client for batched repository metadata.
- Repository discovery across target technical domains, requiring at least 30
  candidates before ranking.
- Deterministic project scoring (career relevance, acceptance probability,
  technical depth, maintainer activity, hardware compatibility, repeat-
  contribution value) with explicit penalties and evidence tracking.
- `oss discover projects`, `oss projects list`, `oss project inspect`,
  `oss project select`.

## [0.1.0] - Foundation

### Added

- Project scaffolding: `uv`-managed Python 3.12+ package, Typer CLI skeleton,
  Ruff/Pyright/pytest tooling, pre-commit hooks, and secret scanning.
- Typed configuration (`pydantic-settings`) with `SecretStr`-backed
  credentials and structured, redacting JSON logging.
- Core domain models and a fully validated workflow state machine covering all
  20 contribution states, with approval gating on external-repository actions.
- SQLite persistence via SQLAlchemy 2 and Alembic, providing resumable
  workflow state through a replayable transition log.
- The hard-coded developer profile used for career-relevance scoring.
- GitHub Actions CI across macOS and Linux, Python 3.12 and 3.13.
