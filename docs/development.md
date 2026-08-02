# Development

## Setup

```bash
git clone https://github.com/hannanrazzaghi/opensource-scout.git
cd opensource-scout
uv sync --all-groups
cp .env.example .env
uv run pre-commit install
```

## Common commands

```bash
uv run oss --help
uv run oss init && uv run oss doctor

uv run pytest                                            # full test suite
uv run pytest --cov=opensource_scout --cov-report=term-missing
uv run pytest tests/unit/test_state_machine.py -q        # targeted

uv run ruff check .
uv run ruff format .
uv run pyright

uv run alembic revision --autogenerate -m "message"       # new migration
uv run alembic upgrade head
```

## Database

Local data (including the SQLite database and any cloned issue-reproduction
workspaces) lives under `~/.opensource-scout/` by default — override with
`OSS_DATA_DIR` / `OSS_WORKSPACE_DIR`. Nothing under that directory is part of
the git repository.

`oss init` creates the schema directly from ORM metadata (fast path for local
development). Production/CI upgrades should go through
`uv run alembic upgrade head` instead, which is what a real deployment would
run against a database created by an earlier version.

## Testing philosophy

- Unit tests assert on plain Python objects and pure functions
  (`domain/`, `workflows/`, `scoring/`) with no I/O.
- Integration tests mock GitHub and OpenAI (`respx`, fakes behind typed
  interfaces) — the default suite never makes a real network or paid API call.
- `tests/fixtures/` holds recorded-shape JSON for GitHub responses used across
  integration tests.

## Releasing

1. Ensure `main` is green: `uv run pytest`, `uv run ruff check .`,
   `uv run pyright`, and CI on the latest push are all passing.
2. Update `CHANGELOG.md` and `docs/progress.md`.
3. Verify installation from a clean clone (`uv sync --frozen --all-groups`,
   `uv run pytest`, `uv run oss doctor`).
4. `git tag -a vX.Y.Z -m "..."` and `git push origin vX.Y.Z`.
5. The `release.yml` workflow re-verifies checks and publishes a GitHub
   release with generated notes.
