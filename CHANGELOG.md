# Changelog

All notable changes to this project are documented here. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

## [0.5.0] - Safe reproduction and implementation workflows

### Added

- Safe, typed command execution: every command is an argument array (never `shell=True`) with a declared working directory, timeout, and risk classification. A fixed blocklist rejects `sudo`/`doas`/`su`, SSH-key/AWS-credential path reads, `--privileged`, `git push --force`, `git reset --hard`, and unscoped recursive deletion, regardless of the declared risk level. Output is redacted before being stored.
- Isolated per-contribution workspaces: clone, checkout, and cleanup, refusing to delete anything outside the workspace root even under a maliciously-crafted contribution ID.
- Issue reproduction: clones the repository, runs a test command sourced from extracted contribution rules, and reports an evidenced `CONFIRMED` / `NOT_REPRODUCED` / `NEEDS_CLARIFICATION` / `ENVIRONMENT_BLOCKED` status — never `CONFIRMED` without a command that actually failed.
- Implementation planning via the reasoning-role LLM, grounded in a deterministic context bundle, producing a structured `ImplementationPlan`. OpenSourceScout does not write code to disk automatically — plans are surfaced for human review.
- Validation: runs the repository's own test/lint/format/typecheck commands and reports an honest per-command status (`PASSED`/`FAILED`/`TIMED_OUT`/`UNAVAILABLE`).
- `oss issue reproduce`, `oss contribution plan/implement/validate/status`, each recording a `workflows.state_machine` transition.

### Fixed

- `OSS_WORKSPACE_DIR`'s default was frozen to the real home directory at class-definition time, so overriding `OSS_DATA_DIR` alone didn't relocate it as expected — `workspace_dir` is now a property derived from `data_dir` unless explicitly overridden.
- Shallow `git clone --depth 50` only fetched the default branch, so checking out any other branch/ref failed; added `--no-single-branch`.

## [0.4.0] - LLM reasoning and context construction

### Added

- Structured LLM output models (`ProjectAssessment`, `IssueAssessment`, `ImplementationPlan`) with field bounds matching the corresponding deterministic score dimensions and required non-empty evidence — malformed or evidence-free output is rejected, not accepted.
- Three-role model router (fast/reasoning/coding) resolving to configured model names; a role with no configured model fails loudly rather than silently falling back to another model.
- OpenAI Responses API client with structured-output parsing, one retry on malformed output, and per-call cost/token recording — no call happens without a Pydantic response model.
- Prompt-hash caching (`llm_cache` table) so an identical (model, task, prompt) request is served without a second billed call.
- Daily/monthly spend budgets and a per-workflow call-count limit, enforced *before* every call against the `llm_calls` audit table.
- Deterministic, bounded repository-context selection (lexical overlap ranking, token-budgeted) — no LLM ever sees an unfiltered repository dump.
- `oss cost today`, `oss cost month`.

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
