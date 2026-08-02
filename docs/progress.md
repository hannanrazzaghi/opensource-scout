# Progress log

Chronological record of completed development steps: what changed, the commit
SHA, what was tested, and the CI result. See [CHANGELOG.md](../CHANGELOG.md)
for the user-facing summary and [docs/architecture.md](architecture.md) for
how the pieces fit together.

## Phase 1 — Public foundation (2026-08-02)

| Commit | Feature | Tests | CI |
|---|---|---|---|
| `cef8533` | `chore: initialize project structure` — `pyproject.toml`, `uv.lock`, `.gitignore`, `LICENSE` (MIT), package tree with stub subpackages | ruff/format clean | n/a (pre-CI) |
| `0e7c8b2` | `feat: add typed configuration and structured logging` — `SecretStr`-backed `Settings`, JSON logging with secret-redaction filter, `.env.example` | manual verification: secrets never appear in `repr()`, redaction confirmed on log output | n/a (pre-CI) |
| `408a618` | `feat: add domain models and workflow state machine` — all 20 `WorkflowState` values, transition table, approval gating on `BRANCH_PUSHED`/`PR_OPENED` | manual smoke test of valid/invalid/gated transitions | n/a (pre-CI) |
| `1113c2c` | `feat: add SQLite persistence with Alembic migrations` — 8 tables, initial revision `a3f003714b1b`, `ensure_database` | `alembic upgrade head` verified against a fresh SQLite file; table list confirmed | n/a (pre-CI) |
| `6f7d8af` | `feat: add hardcoded developer profile` — `HANNAN_PROFILE` with skills/interests/hardware constraints | manual smoke test | n/a (pre-CI) |
| `202fec0` | `feat: add CLI skeleton` — every command from the product spec registered; `init`/`doctor`/`config show`/`profile show` implemented, the rest exit 1 with a phase pointer | manual run of every implemented command | n/a (pre-CI) |
| `b51f3e4` | `test: cover state machine, config redaction, and persistence` — 36 tests across 4 files | `pytest`: **36 passed**; coverage 98–100% on `domain/`, `workflows/`, `db/models.py` | n/a (pre-CI) |
| `3039dfb` | `ci: add macOS and Linux test workflow` — `ci.yml` (macOS + Linux × Python 3.12/3.13), `release.yml`, `.pre-commit-config.yaml`, `.secrets.baseline` | `pre-commit run --all-files`: passed | **Run [30754061641](https://github.com/hannanrazzaghi/opensource-scout/actions/runs/30754061641): all 4 matrix jobs passed** |

Documentation commit (`docs: add project documentation`) follows this log
entry — see the entry below once pushed, plus its own CI run.

**Coverage at end of Phase 1:** 36 tests passing; `domain/enums.py` 100%,
`domain/models.py` 98%, `db/models.py` 100%, `workflows/state_machine.py` 98%.
`cli.py` and `domain/profile.py` are exercised manually but not yet unit
tested (no side effects to assert on beyond what manual verification covered
above); `logging.py` is 69% (the JSON-formatter exception path is untested).

## Phase 2 — GitHub discovery (2026-08-02, branch `feat/github-discovery`)

| Commit | Feature | Tests | CI |
|---|---|---|---|
| `b6ee73f` | `feat: add GitHub REST client with pagination and rate limiting` — pagination via `Link` headers, `X-RateLimit-*` tracking with pre-emptive sleep, ETag conditional caching, Tenacity retry/backoff, bounded concurrency, typed errors | manual respx smoke test | n/a (pre-CI-fix) |
| `a61501b` | `feat: add GraphQL client for batched repository metadata` — one query for metadata + community-health files + recent PR activity | manual respx smoke test | n/a (pre-CI-fix) |
| `350a676` | `feat: implement repository discovery across target domains` — 20 domain search queries, dedup + GraphQL enrichment | manual respx smoke test | n/a (pre-CI-fix) |
| `87ae51f` | `feat: add deterministic project scoring` — six bounded, evidenced dimensions, explicit penalties, no LLM | manual scenario test (archived 50k-star tutorial scores 0; relevant maintained 2k-star project scores 93) | n/a (pre-CI-fix) |
| `55c3f72` | `feat: add project reports and discovery CLI commands` — wires `oss discover projects`, `oss projects list`, `oss project inspect`, `oss project select`; persists to `projects` table; renders anchor/2 alternatives/1 stretch recommendation | manual end-to-end CLI run against mocked GitHub | n/a (pre-CI-fix) |
| `bb5d7aa` | `test: cover pagination, rate limits, caching, and scoring` — 23 new tests (9 GitHub-client integration, 3 discovery integration, 11 scoring unit) | `pytest`: **59 passed total**, zero real network calls (respx-mocked throughout) | discovered CI gap: workflow only triggered on `main`/PRs, not feature-branch pushes |
| `02234a3` | `ci: run CI on feature branch pushes` — added `feat/**` to the push trigger so feature-branch work gets verified before a PR is even opened | n/a | **Run [30754862764](https://github.com/hannanrazzaghi/opensource-scout/actions/runs/30754862764): all 4 matrix jobs passed** |

**Coverage at end of Phase 2:** 59 tests passing. `scoring/project.py` 95%,
`github/discovery.py` 92%, `github/client.py` 88%, `github/graphql.py` 85%,
`github/rate_limit.py` 86%. `github/cache.py` is lower (55%) — the
`SqlAlchemyHttpCache` persistence path is exercised only indirectly via
`reports/project_report.py`, not with a dedicated unit test; a future pass
should add one directly. `reports/project_report.py` and `cli.py` are
exercised via manual end-to-end runs against mocked GitHub responses but have
no automated test coverage yet — worth closing before Phase 3.

## Phase 3 — Issue intelligence (2026-08-02, branch `feat/issue-intelligence`)

| Commit | Feature | Tests | CI |
|---|---|---|---|
| `f2aa07c` | `feat: add issue discovery and competing-work detection` — REST label sweep excluding PRs, GraphQL enrichment for assignees/comments/cross-referenced PRs | manual respx smoke test | pending |
| `106f813` | `feat: add repository contribution-rule extraction` — fetches CONTRIBUTING/SECURITY/LICENSE/tooling files, regex-extracts evidenced rules (test/lint/format/typecheck commands, DCO/CLA, commit conventions, branch rules, PR-title, changelog, design-discussion) | manual respx smoke test | pending |
| `9beceeb` | `feat: add deterministic issue scoring` — six bounded dimensions plus explicit, evidenced rejection reasons (assigned, competing PR, unclear body, private data, GPU hardware, oversized scope, wontfix, security, cosmetic); extracted shared `scoring/keywords.py` to stop duplicating GPU-keyword logic between project and issue scoring | manual scenario test | pending |
| `25ecc11` | `feat: add issue reports and discovery CLI commands` — wires `oss discover issues`, `oss issues list`, `oss issue inspect`, `oss issue select`; persists to `issues` table and stores extracted rules on the parent `projects` row; renders 1 primary + 2 backup recommendation | manual end-to-end CLI run against mocked GitHub | pending |
| `aab8f26` | `test: cover issue scoring, rule extraction, and competing-work detection` — 21 new tests (13 issue-scoring unit, 3 rule-extraction integration, 4 issue-discovery integration, including PR-exclusion and open-vs-closed cross-reference distinction) | `pytest`: **80 passed total**, zero real network calls | pending |

**Coverage at end of Phase 3:** 80 tests passing. `scoring/issue.py` 94%,
`repository/rules.py` 91%, `github/issues.py` 79%. `reports/issue_report.py`
and `cli.py` remain manually-verified only, same gap noted at the end of
Phase 2.

## Phase 4 — LLM reasoning and context construction (2026-08-02, branch `feat/llm-routing`)

| Commit | Feature | Tests | CI |
|---|---|---|---|
| `ab95cf6` | `feat: add structured LLM output models and model router` — `ProjectAssessment`/`IssueAssessment`/`ImplementationPlan` with range/evidence validation; fast/reasoning/coding role resolution that fails loudly on a missing model instead of silently substituting another | manual verification | pending |
| `c9ab269` | `feat: add OpenAI Responses client with cost tracking and caching` — structured-output parsing via `client.responses.parse`, one retry on malformed output, `llm_calls` cost/token recording, daily/monthly/per-workflow budget enforcement, `llm_cache` table (new Alembic revision `e9f96c9f4d37`) for prompt-hash caching | manual respx smoke tests covering cache hit avoiding a second HTTP call, malformed-output retry, and budget rejection; **found and fixed a real bug during smoke testing** — the OpenAI SDK raises `pydantic.ValidationError` directly on unparseable output rather than returning `output_parsed=None`, so the original retry logic never triggered on genuinely malformed text | pending |
| `1409842` | `feat: add deterministic repository-context builder` — lexical-overlap ranking, bounded by file count and token budget; zero-overlap files are never selected regardless of remaining budget | manual verification | pending |
| `f1e8850` | `feat: wire cost tracking CLI commands` — `oss cost today`, `oss cost month` | manual CLI run | pending |
| `83b7d94` | `test: cover LLM structured outputs, routing, budget, cache, and context builder` — 33 new tests (10 structured-output validation, 4 router, 8 budget, 7 context builder, 4 LLM-client integration with mocked OpenAI Responses endpoint) | `pytest`: **113 passed total**, zero real network calls, zero paid API calls | pending |

**Coverage at end of Phase 4:** 113 tests passing. `llm/budget.py` and
`llm/router.py` 100%, `domain/llm_models.py` 100%, `llm/client.py` 91%,
`llm/context.py` 94%. `llm/cache.py`'s `SqlAlchemyLlmCache` persistence path
is exercised only via `InMemoryLlmCache` in tests, same gap as
`github/cache.py`'s `SqlAlchemyHttpCache` noted at the end of Phase 2.
Nothing in the CLI actually calls the LLM layer yet — that wiring happens in
Phase 5 (implementation planning) and Phase 3-style assessment commands
would be a natural follow-up.

## Phase 5 — Safe reproduction and implementation workflows (2026-08-02, branch `feat/execution-safety`)

| Commit | Feature | Tests | CI |
|---|---|---|---|
| `c8661ac` | `feat: add safe typed command execution` — argument-array `CommandSpec`, blocklist for `sudo`/credential paths/`--privileged`/destructive git ops, path-scoped recursive-delete check, output redaction, `CommandRunRow` persistence | manual smoke test covering every blocklist rule plus a scoped-delete allow case and a timeout | pending |
| `622f19e` | `feat: add isolated workspace manager` — per-contribution clone/checkout/cleanup, path-traversal-safe deletion | manual smoke test with a real local git repo (clone, read back a file, cleanup) | pending |
| `3473d74` | `feat: add issue reproduction workflow` — evidenced `CONFIRMED`/`NOT_REPRODUCED`/`NEEDS_CLARIFICATION`/`ENVIRONMENT_BLOCKED` classification from an actual command's exit code | manual smoke test with a real failing pytest test (→ CONFIRMED) and a missing test command (→ NEEDS_CLARIFICATION) | pending |
| `f06693c` | `feat: add implementation planning and validation workflow` — `plan_implementation` (reasoning-role LLM call over a context bundle) and `validate_contribution` (PASSED/FAILED/TIMED_OUT/UNAVAILABLE per command) | manual smoke test surfaced a naming inconsistency (the `UNAVAILABLE` branch didn't prefix its command string like the others) — fixed before commit | pending |
| `bd3f41c` | `feat: wire reproduction and implementation workflow CLI commands` — `oss issue reproduce`, `oss contribution plan/implement/validate/status`, each recording a real state-machine transition | manual end-to-end run against a real GitHub clone (`octocat/Hello-World`) for reproduce, and a mocked-OpenAI full plan→implement→validate→status chain | pending |
| `8160297` | `fix: derive workspace_dir from data_dir instead of a frozen home-directory default` — **found by the automated test suite, not manually**: `Settings.workspace_dir`'s default was evaluated once at class-definition time against the real home directory, so `OSS_DATA_DIR` overrides in tests silently leaked into `~/.opensource-scout/workspaces`, causing a `git clone: destination path already exists` failure. Also fixed shallow `git clone --depth 50` only fetching the default branch (missing `--no-single-branch`), caught by the same test run | the fix is what got the test suite to 146/146 green | pending |
| `4bcd6e7` | `test: cover safe command execution, workspaces, reproduction, and implementation workflow` — 33 new tests (11 command-execution, 6 workspace, 5 reproduction, 5 validation, 4 CLI-level contribution-workflow integration) plus a shared `local_git_repo` fixture so git-dependent tests never hit real network | `pytest`: **146 passed total**, zero real network calls | pending |

**Coverage at end of Phase 5:** 146 tests passing. `execution/command.py` 98%,
`llm/budget.py`/`llm/router.py` 100%, `workflows/reproduction.py` 94%,
`execution/workspace.py` 92%, `workflows/implementation.py` 85%,
`reports/contribution_report.py` 83%. `reports/issue_report.py` and
`reports/project_report.py` remain manually-verified only (same gap noted
since Phase 2/3) — the highest-value follow-up for test coverage at this
point.
