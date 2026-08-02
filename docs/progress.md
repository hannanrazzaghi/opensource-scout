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
