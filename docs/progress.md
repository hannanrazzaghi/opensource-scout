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

## Phase 2 — GitHub discovery

_In progress — entries added as each commit lands._
