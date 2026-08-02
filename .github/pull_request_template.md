## Summary

<!-- What changed and why, in 1-3 bullet points. -->

-

## Test plan

<!-- Exact commands run and their results. -->

- [ ] `uv run ruff check .`
- [ ] `uv run ruff format --check .`
- [ ] `uv run pyright`
- [ ] `uv run pytest --cov=opensource_scout --cov-report=term-missing`
- [ ] `uv run detect-secrets scan --baseline .secrets.baseline`

## Checklist

- [ ] Commits are atomic and use Conventional Commit messages.
- [ ] No secrets, tokens, or `.env` values are included in the diff.
- [ ] Documentation updated if public behavior changed.
- [ ] If this touches external-repository actions, approval gating is
      preserved (see `docs/security.md`).
