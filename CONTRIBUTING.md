# Contributing to OpenSourceScout

This is currently a single-maintainer project developed incrementally in public.
External contributions are welcome once the core workflow (Phases 1–6) has
landed; until then, issues and discussion are the most useful form of
contribution.

## Local setup

```bash
git clone https://github.com/hannanrazzaghi/opensource-scout.git
cd opensource-scout
uv sync --all-groups
cp .env.example .env
uv run pre-commit install
```

## Development cycle

Every change should follow:

```text
Inspect → Plan → Implement → Run targeted tests → Run quality checks
→ Review the full diff → Update docs when needed → Scan for secrets
→ One atomic commit → Push → Confirm CI passes
```

Required checks before any commit:

```bash
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest --cov=opensource_scout --cov-report=term-missing
uv run detect-secrets scan --baseline .secrets.baseline
```

`pre-commit` runs ruff and detect-secrets automatically on `git commit`.

## Commit conventions

Use [Conventional Commits](https://www.conventionalcommits.org/):
`feat:`, `fix:`, `test:`, `docs:`, `refactor:`, `chore:`, `ci:`. Keep commits
small and atomic — one coherent change per commit, tests included when the
change affects behavior.

## Branching

- `main` is always green (CI passing).
- Feature work happens on short-lived `feat/*` branches, merged via pull
  request once checks pass.
- Never force-push `main`, rewrite published history, or bypass failing checks.

## Testing

- Unit tests live in `tests/unit/`, integration tests (mocked GitHub/OpenAI) in
  `tests/integration/`.
- The default test suite makes **no real network calls and no paid API calls**.
  GitHub and OpenAI interactions are mocked with `respx` / fakes behind typed
  interfaces.
- Target ≥80% coverage for workflow, scoring, approval, safety, and
  cost-control modules.

## Safety expectations

Anything that touches an external repository — pushing a branch, opening a PR,
commenting, closing an issue — must go through the approval system described
in [SECURITY.md](SECURITY.md) and [docs/architecture.md](docs/architecture.md).
Do not add code paths that bypass approval gates for external-repository
actions.
